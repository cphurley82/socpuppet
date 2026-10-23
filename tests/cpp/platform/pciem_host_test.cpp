#include "socpuppet/models/pciem_host.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <span>
#include <string>
#include <utility>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/pciem_device.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/fake_pciem_device.h"
#include "tests/cpp/support/line_driver.h"
#include "tests/cpp/support/test_components.h"

namespace socpuppet {

namespace {

using ::testing::ElementsAre;

// The registers the host writes, as the NVMe specification gives them.
constexpr std::uint64_t kAqa = 0x24;
constexpr std::uint64_t kAdminTailDoorbell = 0x1000;

// Who the drive says it is: the puppet's own IDs, and NVMe's class code.
constexpr std::uint16_t kVendorId = 0x5350;
constexpr std::uint16_t kDeviceId = 0xC0DE;
constexpr std::uint32_t kNvmeClass = 0x01'0802;
// How many bytes its register block takes.
constexpr std::uint64_t kFunctionSize = 0x2000;

// 🎭 This machine, stood in by a FakePciem, as the host of a behavioral
// NVMe drive with two interrupt vectors, through a PciemHost.
struct DriveOnAFakeMachine {
  DriveOnAFakeMachine() : platform{WithTheFake(machine)} {
    platform.Add("nvme", "behavioral_nvme", {{"blocks", 64}, {"vectors", 2}});
    platform.Add("host", "pciem_host",
                 {{"vendor_id", kVendorId},
                  {"device_id", kDeviceId},
                  {"class_code", kNvmeClass},
                  {"function_size", kFunctionSize},
                  {"vectors", 2}});
    platform.Bind("host.bar0", "nvme.bar0");
    platform.Bind("nvme.dma", "host.dma");
    platform.Bind("nvme.irq0", "host.irq0");
    platform.Bind("nvme.irq1", "host.irq1");
    platform.Elaborate();
  }

  static Registry WithTheFake(FakePciem& machine) {
    Registry registry = BuiltinComponents();
    AddPciemHost(registry, "pciem_host", [&machine](const PciemShape& shape) {
      machine.opened_as = shape;
      return std::make_unique<FakePciemDevice>(machine);
    });
    return registry;
  }

  PciemHost& Host() { return platform.ModuleAt<PciemHost>("host"); }

  // Lets the current moment finish, so that the host makes the writes it
  // was given.
  void LetTheHostMakeItsWrites() { platform.TimeToNextActivity(); }

  // The bytes of the drive's register at `offset`, as a debugger sees them.
  std::array<std::byte, 4> DriveRegister(std::uint64_t offset) {
    std::array<std::byte, 4> bytes{};
    platform.DebugRead("host.bar0", offset, bytes);
    return bytes;
  }

  FakePciem machine;
  Platform platform;
};

// A function of the test's own, a bus master that runs `function`, on this
// machine as stood in by a FakePciem. The host's `bar0` goes to a memory,
// as the function's registers, and the function's interrupt line for
// kDrivenVector is driven by `line`.
struct FunctionOnAFakeMachine {
  // The vector whose line `line` drives: not the first, so that sending it
  // is not sending the one there would be anyway.
  static constexpr unsigned kDrivenVector = 1;

  explicit FunctionOnAFakeMachine(
      const std::function<void(BusDriver&)>& function,
      const Drive& line = [](LineDriver&) {})
      : platform{WithTheFunction(machine, function, line)} {
    platform.Add("host", "pciem_host",
                 {{"vendor_id", kVendorId},
                  {"device_id", kDeviceId},
                  {"class_code", kNvmeClass},
                  {"function_size", kFunctionSize},
                  {"vectors", 2}});
    platform.Add("registers", "memory", {{"size", kFunctionSize}});
    platform.Add("function", "function_driver");
    platform.Add("line", "line_driver");
    platform.Bind("host.bar0", "registers.socket");
    platform.Bind("function.socket", "host.dma");
    platform.Bind("line.line", "host.irq" + std::to_string(kDrivenVector));
    platform.Elaborate();
  }

  static Registry WithTheFunction(
      FakePciem& machine, const std::function<void(BusDriver&)>& function,
      const Drive& line) {
    Registry registry = DriveOnAFakeMachine::WithTheFake(machine);
    AddBusDriver(registry, "function_driver", function);
    AddLineDriver(registry, "line_driver", line);
    return registry;
  }

  // Puts `bytes` in the host's memory at `address`.
  void PutInHostMemory(std::uint64_t address,
                       std::span<const std::uint8_t> bytes) {
    std::ranges::copy(
        bytes, machine.memory.begin() + static_cast<std::ptrdiff_t>(address));
  }
  // The `size` bytes of the host's memory at `address`.
  std::span<const std::uint8_t> HostMemory(std::uint64_t address,
                                           std::size_t size) {
    return std::span(machine.memory).subspan(address, size);
  }

  FakePciem machine;
  Platform platform;
};

TEST(WhenAPciemHostIsMade, ItsDeviceIsOpenedInTheShapeItsParametersSay) {
  DriveOnAFakeMachine rig;

  const PciemShape& shape = rig.machine.opened_as;
  EXPECT_EQ(shape.identity.vendor_id, kVendorId);
  EXPECT_EQ(shape.identity.device_id, kDeviceId);
  EXPECT_EQ(shape.identity.class_code, kNvmeClass);
  EXPECT_EQ(shape.function_size, kFunctionSize);
  EXPECT_EQ(shape.vectors, 2U);
}

TEST(WhenTheHostsWritesAreTaken, TheyAreMadeOnTheFunctionsRegistersInOrder) {
  DriveOnAFakeMachine rig;
  const std::array<HostWrite, 2> writes{
      {{.offset = kAqa, .size = 4, .data = 0x001F'001F},
       {.offset = kAqa, .size = 4, .data = 0x0003'0003}}};

  rig.Host().Take(writes);
  rig.LetTheHostMakeItsWrites();

  EXPECT_THAT(rig.DriveRegister(kAqa),
              ElementsAre(std::byte{0x03}, std::byte{0}, std::byte{0x03},
                          std::byte{0}));
}

TEST(WhenTheFunctionRefusesAWrite, ItIsCountedAsRefused) {
  DriveOnAFakeMachine rig;
  // A doorbell, which a drive that is not enabled has no queue for.
  const std::array<HostWrite, 2> writes{
      {{.offset = kAqa, .size = 4, .data = 0x001F'001F},
       {.offset = kAdminTailDoorbell, .size = 4, .data = 1}}};

  rig.Host().Take(writes);
  rig.LetTheHostMakeItsWrites();

  EXPECT_EQ(rig.Host().Counts().refused_writes, 1U);
}

TEST(WhenTheFunctionReadsTheHostsMemory, TheBytesComeFromTheDevice) {
  std::array<std::uint8_t, 4> read{};
  FunctionOnAFakeMachine rig(
      [&](BusDriver& function) { function.Read(0x100, read); });
  rig.PutInHostMemory(0x100, std::array<std::uint8_t, 4>{1, 2, 3, 4});

  rig.platform.Run();

  EXPECT_THAT(read, ElementsAre(1, 2, 3, 4));
}

TEST(WhenTheFunctionWritesTheHostsMemory, TheBytesGoToTheDevice) {
  FunctionOnAFakeMachine rig([](BusDriver& function) {
    function.Write(0x100, std::array<std::uint8_t, 4>{1, 2, 3, 4});
  });

  rig.platform.Run();

  EXPECT_THAT(rig.HostMemory(0x100, 4), ElementsAre(1, 2, 3, 4));
}

TEST(WhenTheDeviceRefusesATransfer, TheFunctionGetsAnErrorResponse) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  FunctionOnAFakeMachine rig([&](BusDriver& function) {
    std::array<std::uint8_t, 4> read{};
    response = function.Read(0x100, read);
  });
  rig.machine.refuses_dma = true;

  rig.platform.Run();

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
}

// A function with nothing to do of its own.
void Idle(BusDriver&) {}

TEST(WhenAnInterruptLineRises, ThatVectorIsSentToTheHost) {
  FunctionOnAFakeMachine rig(Idle, [](LineDriver& line) { line.Set(true); });

  rig.platform.Run();

  EXPECT_THAT(rig.machine.sent,
              ElementsAre(FunctionOnAFakeMachine::kDrivenVector));
}

}  // namespace

}  // namespace socpuppet
