#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
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
  kControl = 0x00,
  kStatus = 0x04,
  kInterruptEnable = 0x08,
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
    command[index] =
        static_cast<std::uint8_t>(index + (std::size_t{7} * command_id) + 1);
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

  // What the host finds in the first slot of its admin completion queue:
  // which command the completion is for, and how it went. They are in the
  // completion's last four bytes: the command's identifier, then the phase
  // bit with the status above it.
  int CommandIdOfTheFirstCompletion() {
    return LoadLittleEndian<std::uint16_t>(
        HostMemoryAt(kAdminCompletionQueue + 12, 2));
  }
  int StatusOfTheFirstCompletion() {
    return LoadLittleEndian<std::uint16_t>(
               HostMemoryAt(kAdminCompletionQueue + 14, 2)) >>
           1;
  }

  // A register of the CPU's block as a debugger sees it, or nothing if the
  // frontend would not show it. What comes back is not zeros unless the
  // frontend put them there.
  std::optional<std::uint32_t> DebugReadCpu32(std::uint64_t offset) {
    std::array<std::uint8_t, 4> seen{0xA5, 0xA5, 0xA5, 0xA5};
    if (!platform.DebugRead("cpu.socket", offset,
                            std::as_writable_bytes(std::span{seen}))) {
      return std::nullopt;
    }
    return LoadLittleEndian<std::uint32_t>(seen);
  }

  // How many times a line has risen, and whether it is high now. `line` is
  // "irq0" or "irq1", to the host, or "cpu_irq".
  int Rises(const std::string& line) {
    return platform.ModuleAt<LineWatcher>(line).Rises();
  }
  bool IsHigh(const std::string& line) {
    return platform.ModuleAt<LineWatcher>(line).line->read();
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
  EXPECT_EQ(fixture.CommandIdOfTheFirstCompletion(), 7);
  EXPECT_EQ(fixture.StatusOfTheFirstCompletion(), 0x02);
}

// The frontend works alongside the host, not inside the host's write: when
// the write to the doorbell returns, the command has not been fetched. It
// is fetched in the next delta cycle, in which the host and the frontend
// may run in either order, so the host gives it two.
TEST(WhenAHostHasJustRungADoorbellOfAnNvmeFrontend,
     NoCommandWaitsForTheCpuYetAndOneDoesOnceTheFrontendHasHadItsTurn) {
  HostAndCpuWithAnNvmeFrontend* wired = nullptr;
  std::optional<std::uint32_t> when_the_write_returned;
  std::optional<std::uint32_t> afterwards;
  HostAndCpuWithAnNvmeFrontend fixture{
      [&](BusDriver& host) {
        HostEnables(host);
        host.Write32(kAdminTailDoorbell, 1);
        when_the_write_returned = wired->DebugReadCpu32(kStatus);
        host.WaitFor(sc_core::SC_ZERO_TIME);
        host.WaitFor(sc_core::SC_ZERO_TIME);
        afterwards = wired->DebugReadCpu32(kStatus);
      },
      [](BusDriver& cpu) { FirmwareComesReady(cpu); }};
  wired = &fixture;
  fixture.PutInHostMemory(kAdminSubmissionQueue, SomeCommand(7));

  fixture.platform.Run();

  EXPECT_EQ(when_the_write_returned, 0U);
  EXPECT_EQ(afterwards, kCommandWaiting);
}

// One rise for each command: the line falls when the firmware has dealt
// with one, and rises again when the next has been fetched. An interrupt
// controller that hears a rise hears every command.
TEST(WhenTwoCommandsComeAndTheCpuAskedToBeInterruptedForACommand,
     TheCpusLineRisesOnceForEachAndFallsWhenBothAreDealtWith) {
  HostAndCpuWithAnNvmeFrontend fixture{
      [](BusDriver& host) {
        HostEnables(host);
        host.Write32(kAdminTailDoorbell, 2);
      },
      [](BusDriver& cpu) {
        cpu.Write32(kInterruptEnable, kCommandWaiting);
        FirmwareComesReady(cpu);
        FirmwareDealsWithACommand(cpu, /*status=*/0);
        FirmwareDealsWithACommand(cpu, /*status=*/0);
      }};
  fixture.PutInHostMemory(kAdminSubmissionQueue, SomeCommand(7));
  fixture.PutInHostMemory(kAdminSubmissionQueue + kCommandBytes,
                          SomeCommand(8));

  fixture.platform.Run();

  EXPECT_EQ(fixture.Rises("cpu_irq"), 2);
  EXPECT_FALSE(fixture.IsHigh("cpu_irq"));
}

// The admin queue's vector is the first. The line stays high until the
// host says how far it has read, by writing the queue's head doorbell.
TEST(WhenAnNvmeFrontendPostsACompletion,
     TheHostsLineRisesAndFallsWhenTheHostAcknowledges) {
  HostAndCpuWithAnNvmeFrontend* wired = nullptr;
  bool high_before_the_acknowledgement = false;
  HostAndCpuWithAnNvmeFrontend fixture{
      [&](BusDriver& host) {
        HostEnables(host);
        host.Write32(kAdminTailDoorbell, 1);
        high_before_the_acknowledgement =
            WaitUntil(host, [&] { return wired->IsHigh("irq0"); });
        host.Write32(kAdminHeadDoorbell, 1);
      },
      [](BusDriver& cpu) {
        FirmwareComesReady(cpu);
        FirmwareDealsWithACommand(cpu, /*status=*/0);
      }};
  wired = &fixture;
  fixture.PutInHostMemory(kAdminSubmissionQueue, SomeCommand(7));

  fixture.platform.Run();

  EXPECT_TRUE(high_before_the_acknowledgement);
  EXPECT_EQ(fixture.Rises("irq0"), 1);
  EXPECT_FALSE(fixture.IsHigh("irq0"));
  EXPECT_EQ(fixture.Rises("irq1"), 0);
}

// The host's write, the CPU's write and the end of the frontend's own work
// all change what the lines should say. Here the host and the CPU write in
// the same delta cycle as each other, again and again, which a line with
// two writers would not survive.
TEST(WhenTheHostAndTheCpuWriteToAnNvmeFrontendInTheSameDeltaCycle,
     TheRunCarriesOn) {
  HostAndCpuWithAnNvmeFrontend fixture{
      [](BusDriver& host) {
        for (int turn = 0; turn < 4; ++turn) {
          host.Write32(kCc, turn % 2 == 0 ? 1 : 0);
          host.WaitFor(sc_core::SC_ZERO_TIME);
        }
      },
      [](BusDriver& cpu) {
        for (int turn = 0; turn < 4; ++turn) {
          cpu.Write32(kInterruptEnable, turn % 2 == 0 ? kEnabled : 0);
          cpu.WaitFor(sc_core::SC_ZERO_TIME);
        }
      }};

  EXPECT_NO_THROW(fixture.platform.Run());
}

TEST(WhenADebuggerLooksAtARegisterOfAnNvmeFrontendsCpu, ItSeesWhatTheCpuWould) {
  HostAndCpuWithAnNvmeFrontend fixture{
      [](BusDriver& host) { host.Write32(kCc, 1); }, [](BusDriver&) {}};
  fixture.platform.Run();

  EXPECT_EQ(fixture.DebugReadCpu32(kStatus), kEnabled);
}

// A debugger can look and cannot touch: a completion posted this way, or a
// status acknowledged, would be something the firmware never did.
TEST(WhenADebuggerWritesToARegisterOfAnNvmeFrontendsCpu, TheWriteIsDeclined) {
  const std::array<std::uint8_t, 4> acknowledgement{kEnabled, 0, 0, 0};
  HostAndCpuWithAnNvmeFrontend fixture{
      [](BusDriver& host) { host.Write32(kCc, 1); }, [](BusDriver&) {}};
  fixture.platform.Run();

  const bool answered = fixture.platform.DebugWrite(
      "cpu.socket", kStatus, std::as_bytes(std::span{acknowledgement}));

  EXPECT_FALSE(answered);
  EXPECT_EQ(fixture.DebugReadCpu32(kStatus), kEnabled);
}

TEST(WhenAnNvmeFrontendRefusesAnAccess, WhoeverMadeItGetsAnAddressError) {
  tlm::tlm_response_status hosts = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status cpus = tlm::TLM_INCOMPLETE_RESPONSE;
  HostAndCpuWithAnNvmeFrontend fixture{
      // The doorbell of a queue that does not exist: nothing is enabled.
      [&](BusDriver& host) { hosts = host.Write32(kAdminTailDoorbell, 1); },
      // A completion, with no command waiting.
      [&](BusDriver& cpu) { cpus = cpu.Write32(kCompletionPost, 1); }};

  fixture.platform.Run();

  EXPECT_EQ(hosts, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(cpus, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

// A host need not use every vector, and firmware may poll the status
// register and never look at its line.
TEST(WhenTheInterruptLinesOfAnNvmeFrontendAreLeftUnconnected,
     ThePlatformStillElaborates) {
  Platform platform{HostAndCpuWithAnNvmeFrontend::WithDriversAndWatchers(
      [](BusDriver&) {}, [](BusDriver&) {})};
  platform.Add("host", "host_driver");
  platform.Add("cpu", "cpu_driver");
  platform.Add("frontend", "nvme_frontend", {{"vectors", 2}});
  platform.Add("host_memory", "memory", {{"size", 0x1'0000}});
  platform.Bind("host.socket", "frontend.bar0");
  platform.Bind("cpu.socket", "frontend.cpu");
  platform.Bind("frontend.dma", "host_memory.socket");

  EXPECT_NO_THROW(platform.Elaborate());
}

}  // namespace socpuppet
