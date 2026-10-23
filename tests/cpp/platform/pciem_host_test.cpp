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
#include <vector>

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

// The drive's registers, as the NVMe specification gives them.
constexpr std::uint64_t kCap = 0x00;
constexpr std::uint64_t kVs = 0x08;
constexpr std::uint64_t kCc = 0x14;
constexpr std::uint64_t kCsts = 0x1C;
constexpr std::uint64_t kAqa = 0x24;
constexpr std::uint64_t kAdminTailDoorbell = 0x1000;
constexpr std::uint64_t kAdminHeadDoorbell = 0x1004;

// Who the drive says it is: the puppet's own IDs, and NVMe's class code.
constexpr std::uint16_t kVendorId = 0x5350;
constexpr std::uint16_t kDeviceId = 0xC0DE;
constexpr std::uint32_t kNvmeClass = 0x01'0802;
// How many bytes its register block takes.
constexpr std::uint64_t kFunctionSize = 0x2000;

// A byte no register of the drive says, so that a copy of one that says 0
// shows.
constexpr std::uint8_t kNoise = 0xA5;

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
      return std::make_unique<FakePciemDevice>(machine, shape);
    });
    return registry;
  }

  PciemHost& Host() { return platform.ModuleAt<PciemHost>("host"); }

  // Lets the current moment finish, so that the host makes the writes it
  // was given.
  void LetTheHostMakeItsWrites() { platform.TimeToNextActivity(); }

  // The `size` bytes of the drive's registers at `offset`, as a debugger
  // sees them.
  std::vector<std::uint8_t> DriveRegister(std::uint64_t offset,
                                          std::size_t size = 4) {
    std::vector<std::uint8_t> bytes(size);
    platform.DebugRead("host.bar0", offset,
                       std::as_writable_bytes(std::span{bytes}));
    return bytes;
  }

  // Fills pciem's copy of BAR0 with kNoise, as the memory pciem sets aside
  // may hold.
  void FillWhatTheHostReadsWithNoise() {
    std::ranges::fill(machine.bar0, kNoise);
  }

  // The `size` bytes at `offset` of pciem's copy of BAR0, which is what
  // the host reads.
  std::vector<std::uint8_t> WhatTheHostReads(std::uint64_t offset,
                                             std::size_t size = 4) {
    const auto at = machine.bar0.begin() + static_cast<std::ptrdiff_t>(offset);
    return {at, at + static_cast<std::ptrdiff_t>(size)};
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

  PciemHost& Host() { return platform.ModuleAt<PciemHost>("host"); }

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

TEST(WhenTheHostIsServiced, TheWritesPciemPostedAreMadeOnTheFunctionInOrder) {
  DriveOnAFakeMachine rig;
  rig.machine.posted = {{.offset = kAqa, .size = 4, .data = 0x001F'001F},
                        {.offset = kAqa, .size = 4, .data = 0x0003'0003}};

  rig.Host().Service();
  rig.LetTheHostMakeItsWrites();

  EXPECT_THAT(rig.DriveRegister(kAqa), ElementsAre(0x03, 0, 0x03, 0));
}

TEST(WhenTheFunctionRefusesAWrite, ItIsCountedAsRefused) {
  DriveOnAFakeMachine rig;
  // A doorbell, which a drive that is not enabled has no queue for.
  rig.machine.posted = {{.offset = kAqa, .size = 4, .data = 0x001F'001F},
                        {.offset = kAdminTailDoorbell, .size = 4, .data = 1}};

  rig.Host().Service();
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

// The host acknowledging the first completion on the admin queue.
constexpr HostWrite kAcknowledgeAnAdminCompletion{
    .offset = kAdminHeadDoorbell, .size = 4, .data = 1};

// A function's line stays high while completions wait to be read, and
// the host is sent a vector only when it rises.
TEST(WhenTheHostAcknowledgesCompletionsWhileTheLineStaysHigh,
     TheVectorIsSentAgain) {
  FunctionOnAFakeMachine rig(Idle, [](LineDriver& line) { line.Set(true); });
  rig.platform.Run();

  rig.machine.posted = {kAcknowledgeAnAdminCompletion};
  rig.Host().Service();
  rig.platform.Run();

  EXPECT_THAT(rig.machine.sent,
              ElementsAre(FunctionOnAFakeMachine::kDrivenVector,
                          FunctionOnAFakeMachine::kDrivenVector));
}

TEST(WhenTheHostAcknowledgesCompletionsOnceTheLineHasFallen,
     TheVectorIsNotSentAgain) {
  FunctionOnAFakeMachine rig(Idle, [](LineDriver& line) {
    line.Set(true);
    line.WaitFor(sc_core::sc_time(1, sc_core::SC_US));
    line.Set(false);
  });
  rig.platform.Run();

  rig.machine.posted = {kAcknowledgeAnAdminCompletion};
  rig.Host().Service();
  rig.platform.Run();

  EXPECT_THAT(rig.machine.sent,
              ElementsAre(FunctionOnAFakeMachine::kDrivenVector));
}

// The host setting CC.EN, which enables the drive.
constexpr HostWrite kEnable{.offset = kCc, .size = 4, .data = 1};

TEST(WhenTheHostIsRefreshed, CapVsAndCstsAreCopiedInAsTheFunctionSaysThem) {
  DriveOnAFakeMachine rig;
  rig.FillWhatTheHostReadsWithNoise();
  // So that CSTS says something other than it did at the start.
  rig.machine.posted = {kEnable};
  rig.Host().Service();
  rig.LetTheHostMakeItsWrites();

  rig.Host().Refresh();

  EXPECT_EQ(rig.WhatTheHostReads(kCap, 8), rig.DriveRegister(kCap, 8));
  EXPECT_EQ(rig.WhatTheHostReads(kVs), rig.DriveRegister(kVs));
  EXPECT_EQ(rig.WhatTheHostReads(kCsts), rig.DriveRegister(kCsts));
}

// pciem keeps the host's writes in its copy of BAR0, which is what the host
// reads back.
TEST(WhenTheHostIsRefreshed, TheRegistersTheHostWritesAreNotCopiedIn) {
  DriveOnAFakeMachine rig;
  rig.FillWhatTheHostReadsWithNoise();

  rig.Host().Refresh();

  EXPECT_THAT(rig.WhatTheHostReads(kAqa),
              ElementsAre(kNoise, kNoise, kNoise, kNoise));
}

}  // namespace

}  // namespace socpuppet
