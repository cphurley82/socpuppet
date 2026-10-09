#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <span>
#include <string>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/test_components.h"

namespace socpuppet {

namespace {

// The registers the host sees, as the NVMe specification gives them. The
// doorbells follow the controller registers: the admin submission queue's
// tail first, then the admin completion queue's head.
enum HostRegister : std::uint64_t {
  kCc = 0x14,
  kCsts = 0x1C,
  kAqa = 0x24,
  kAsq = 0x28,
  kAcq = 0x30,
  kAdminTailDoorbell = 0x1000,
  kAdminHeadDoorbell = 0x1004,
};

// The registers the SSD's CPU sees, as docs/models/nvme-frontend.md gives
// them.
enum CpuRegister : std::uint64_t {
  kStatus = 0x00,
  kInterruptEnable = 0x04,
  kControl = 0x08,
  kCompletionStatus = 0x18,
  kCompletionPost = 0x1C,
  kCommand = 0x40,
};

// The bits of the CPU's status register, and the one bit of its control
// register.
enum StatusBit : std::uint32_t {
  kEnabled = 1U << 0,
  kCommandWaiting = 1U << 2,
};
constexpr std::uint32_t kReady = 1U << 0;

// Where the host of these tests keeps its admin queues, of four entries
// each, in a memory of 64 KiB.
constexpr std::uint64_t kAdminSubmissionQueue = 0x1000;
constexpr std::uint64_t kAdminCompletionQueue = 0x2000;

constexpr std::size_t kCommandBytes = 64;

// A command with an identifier, and otherwise bytes that are all different
// and that differ from another command's. The identifier is in the third
// and fourth bytes.
std::vector<std::uint8_t> SomeCommand(std::uint16_t command_id) {
  std::vector<std::uint8_t> command(kCommandBytes);
  for (std::size_t index = 0; index < command.size(); ++index) {
    command[index] = static_cast<std::uint8_t>(index + (7 * command_id) + 1);
  }
  StoreLittleEndian(command_id, std::span{command}.subspan(2));
  return command;
}

// Waits a delta cycle at a time until `is_so`. Nothing here takes
// simulated time, so what is waited for comes within a few delta cycles:
// the limit is only there so that something that never comes fails the
// test and does not hang it.
bool WaitUntil(BusDriver& driver, const std::function<bool()>& is_so) {
  for (int delta = 0; delta < 100; ++delta) {
    if (is_so()) return true;
    driver.WaitFor(sc_core::SC_ZERO_TIME);
  }
  return false;
}

// An NVMe frontend with two interrupt vectors, between a host and the
// SSD's CPU, each a bus master that runs a body of the test's. The host
// has 64 KiB of memory, which the frontend reaches for its DMA, and the
// test has its eyes on the three interrupt lines.
struct HostAndCpuWithAnNvmeFrontend {
  HostAndCpuWithAnNvmeFrontend(const std::function<void(BusDriver&)>& host,
                               const std::function<void(BusDriver&)>& cpu)
      : platform{WithDriversAndWatchers(host, cpu)} {
    platform.Add("host", "host_driver");
    platform.Add("cpu", "cpu_driver");
    platform.Add("frontend", "nvme_frontend", {{"vectors", 2}});
    platform.Add("host_memory", "memory", {{"size", 0x1'0000}});
    platform.Add("irq0", "line_watcher");
    platform.Add("irq1", "line_watcher");
    platform.Add("cpu_irq", "line_watcher");
    platform.Bind("host.socket", "frontend.bar0");
    platform.Bind("cpu.socket", "frontend.cpu");
    platform.Bind("frontend.dma", "host_memory.socket");
    platform.Bind("frontend.irq0", "irq0.line");
    platform.Bind("frontend.irq1", "irq1.line");
    platform.Bind("frontend.cpu_irq", "cpu_irq.line");
    platform.Elaborate();
  }

  static Registry WithDriversAndWatchers(
      const std::function<void(BusDriver&)>& host,
      const std::function<void(BusDriver&)>& cpu) {
    Registry registry = BuiltinComponents();
    AddBusDriver(registry, "host_driver", host);
    AddBusDriver(registry, "cpu_driver", cpu);
    AddLineWatcher(registry, "line_watcher");
    return registry;
  }

  // What the host's memory holds, and putting bytes there, the way a
  // debugger would.
  std::vector<std::uint8_t> HostMemoryAt(std::uint64_t address,
                                         std::size_t length) {
    std::vector<std::uint8_t> data(length);
    platform.DebugRead("frontend.dma", address,
                       std::as_writable_bytes(std::span{data}));
    return data;
  }
  void PutInHostMemory(std::uint64_t address,
                       const std::vector<std::uint8_t>& data) {
    platform.DebugWrite("frontend.dma", address,
                        std::as_bytes(std::span{data}));
  }

  Platform platform;
};

// What a host does to enable the controller: it says where its admin
// queues are, sets CC.EN, and waits for the controller to say it is ready.
bool HostEnables(BusDriver& host) {
  host.Write32(kAqa, 3U << 16 | 3U);
  host.Write64(kAsq, kAdminSubmissionQueue);
  host.Write64(kAcq, kAdminCompletionQueue);
  host.Write32(kCc, 1);
  return WaitUntil(host, [&] { return (host.Read32(kCsts) & 1U) != 0; });
}

// What firmware does when the host enables the controller: it notices,
// acknowledges, and says it is ready.
bool FirmwareComesReady(BusDriver& cpu) {
  if (!WaitUntil(cpu, [&] { return (cpu.Read32(kStatus) & kEnabled) != 0; })) {
    return false;
  }
  cpu.Write32(kStatus, kEnabled);
  cpu.Write32(kControl, kReady);
  return true;
}

// What firmware does with a command: it waits for one, reads it, and has a
// completion posted that says how it went. Returns the command, or nothing
// if none came.
std::vector<std::uint8_t> FirmwareDealsWithACommand(BusDriver& cpu,
                                                    std::uint32_t status) {
  if (!WaitUntil(
          cpu, [&] { return (cpu.Read32(kStatus) & kCommandWaiting) != 0; })) {
    return {};
  }
  std::vector<std::uint8_t> command(kCommandBytes);
  cpu.Read(kCommand, command);
  cpu.Write32(kCompletionStatus, status);
  cpu.Write32(kCompletionPost, 1);
  return command;
}

}  // namespace

// The whole of what the frontend is for, once through: the host's command
// reaches the firmware, and the firmware's verdict reaches the host.
TEST(WhenAHostSubmitsACommandThroughAnNvmeFrontend,
     TheFirmwareReadsItAndTheHostFindsItsCompletion) {
  std::vector<std::uint8_t> seen_by_firmware;
  HostAndCpuWithAnNvmeFrontend fixture{
      [](BusDriver& host) {
        HostEnables(host);
        host.Write32(kAdminTailDoorbell, 1);
      },
      [&](BusDriver& cpu) {
        FirmwareComesReady(cpu);
        seen_by_firmware = FirmwareDealsWithACommand(cpu, /*status=*/0x02);
      }};
  fixture.PutInHostMemory(kAdminSubmissionQueue, SomeCommand(7));

  fixture.platform.Run();

  EXPECT_EQ(seen_by_firmware, SomeCommand(7));
  // The completion's last four bytes: the command's identifier, then the
  // phase bit and the status, which is shifted up past it.
  EXPECT_EQ(fixture.HostMemoryAt(kAdminCompletionQueue + 12, 4),
            (std::vector<std::uint8_t>{7, 0, 0x01 | (0x02 << 1), 0}));
}

}  // namespace socpuppet
