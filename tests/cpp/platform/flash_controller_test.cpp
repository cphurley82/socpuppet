#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <span>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/test_components.h"

namespace socpuppet {

namespace {

// The controller's registers, each 32 bits wide, as its page in
// docs/models/ gives them.
constexpr std::uint64_t kCommand = 0x00;
constexpr std::uint64_t kStatus = 0x04;
constexpr std::uint64_t kInterruptEnable = 0x08;
constexpr std::uint64_t kBlock = 0x0C;
constexpr std::uint64_t kPage = 0x10;
constexpr std::uint64_t kLocal = 0x14;

// What can be written to the command register.
constexpr std::uint32_t kReadPage = 1;
constexpr std::uint32_t kProgramPage = 2;

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;
constexpr std::uint32_t kBusy = 1U << 2;

// A page is 16 bytes on the chip these tests use.
constexpr std::size_t kPageSize = 16;

// A page of data in which no two neighbouring bytes are the same.
std::vector<std::uint8_t> SomePage() {
  std::vector<std::uint8_t> data(kPageSize);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(1 + index);
  }
  return data;
}

// A flash controller with a small chip behind it (4 blocks of 8 pages of
// 16 bytes), 256 bytes of the SSD's own memory at address 0, a bus master
// in the CPU's place, and a test's eyes on the interrupt line. `body` is
// what the CPU does.
struct CpuWithAFlashController {
  explicit CpuWithAFlashController(const std::function<void(BusDriver&)>& body)
      : platform{WithADriverAndAWatcher(body)} {
    platform.Add("cpu", "bus_driver");
    platform.Add("flash", "flash_controller");
    platform.Add("nand", "ideal_nand",
                 {{"blocks", 4}, {"pages_per_block", 8}, {"page_size", 16}});
    platform.Add("buffer", "memory", {{"size", 0x100}});
    platform.Add("watcher", "line_watcher");
    platform.Bind("cpu.socket", "flash.cpu");
    platform.Bind("flash.local", "buffer.socket");
    platform.Bind("flash.nand", "nand.socket");
    platform.Bind("flash.irq", "watcher.line");
    platform.Elaborate();
  }

  static Registry WithADriverAndAWatcher(
      const std::function<void(BusDriver&)>& body) {
    Registry registry = BuiltinComponents();
    AddBusDriver(registry, "bus_driver", body);
    AddLineWatcher(registry, "line_watcher");
    return registry;
  }

  // What the SSD's memory holds at `address`, a page's worth, and putting
  // a page there, the way a debugger would.
  std::vector<std::uint8_t> BufferAt(std::uint64_t address) {
    std::vector<std::uint8_t> data(kPageSize);
    platform.DebugRead("flash.local", address,
                       std::as_writable_bytes(std::span{data}));
    return data;
  }
  void PutInBuffer(std::uint64_t address,
                   const std::vector<std::uint8_t>& data) {
    platform.DebugWrite("flash.local", address, std::as_bytes(std::span{data}));
  }

  LineWatcher& InterruptLine() {
    return platform.ModuleAt<LineWatcher>("watcher");
  }

  Platform platform;
};

// Tells the controller to do something with one page, and waits until it
// says it is no longer busy, the way firmware that polls would.
void Command(BusDriver& cpu, std::uint32_t command, std::uint32_t block,
             std::uint32_t page, std::uint32_t local) {
  cpu.Write32(kBlock, block);
  cpu.Write32(kPage, page);
  cpu.Write32(kLocal, local);
  cpu.Write32(kCommand, command);
  while ((cpu.Read32(kStatus) & kBusy) != 0) {
    cpu.WaitFor(sc_core::SC_ZERO_TIME);
  }
}

}  // namespace

TEST(WhenACpuHasAFlashControllerProgramAPageAndReadItBack,
     ThePageComesBackToTheSsdsMemory) {
  CpuWithAFlashController fixture{[](BusDriver& cpu) {
    Command(cpu, kProgramPage, 2, 5, 0x40);
    Command(cpu, kReadPage, 2, 5, 0x80);
  }};
  fixture.PutInBuffer(0x40, SomePage());

  fixture.platform.Run();

  EXPECT_EQ(fixture.BufferAt(0x80), SomePage());
}

// The controller works alongside the CPU, not inside the CPU's write: when
// the write to the command register returns, nothing has been done yet.
// The work is done in the next delta cycle, in which the CPU and the
// controller may run in either order, so the CPU gives it two.
TEST(WhenACpuHasJustToldAFlashControllerToDoSomething,
     ItIsBusyWhenTheWriteReturnsAndDoneOnceItHasHadItsTurn) {
  std::uint32_t when_the_write_returned = 0;
  std::uint32_t afterwards = 0;
  CpuWithAFlashController fixture{[&](BusDriver& cpu) {
    cpu.Write32(kCommand, kReadPage);
    when_the_write_returned = cpu.Read32(kStatus);
    cpu.WaitFor(sc_core::SC_ZERO_TIME);
    cpu.WaitFor(sc_core::SC_ZERO_TIME);
    afterwards = cpu.Read32(kStatus);
  }};

  fixture.platform.Run();

  EXPECT_EQ(when_the_write_returned, kBusy);
  EXPECT_EQ(afterwards, kDone);
}

TEST(WhenAFlashControllerFinishesACommandWithItsInterruptEnabled,
     ItsLineRisesAndStaysHigh) {
  CpuWithAFlashController fixture{[](BusDriver& cpu) {
    cpu.Write32(kInterruptEnable, kDone);
    cpu.Write32(kCommand, kReadPage);
  }};

  fixture.platform.Run();

  EXPECT_EQ(fixture.InterruptLine().Rises(), 1);
  EXPECT_TRUE(fixture.InterruptLine().line->read());
}

TEST(WhenTheCpuClearsTheStatusBitThatInterruptedIt,
     TheFlashControllersLineFalls) {
  CpuWithAFlashController* wired = nullptr;
  CpuWithAFlashController fixture{[&](BusDriver& cpu) {
    cpu.Write32(kInterruptEnable, kDone);
    cpu.Write32(kCommand, kReadPage);
    wired->InterruptLine().WaitForRises(1, sc_core::sc_time(1, sc_core::SC_MS));
    cpu.Write32(kStatus, kDone);
  }};
  wired = &fixture;

  fixture.platform.Run();

  EXPECT_EQ(fixture.InterruptLine().Rises(), 1);
  EXPECT_FALSE(fixture.InterruptLine().line->read());
}

// The CPU's write and the end of the controller's work both change what
// the line should say. Here they come in the same delta cycle, which a
// line with two writers would not survive.
TEST(WhenTheCpuWritesToAFlashControllerInTheDeltaCycleItsWorkIsDoneIn,
     TheRunCarriesOnAndTheLineSaysWhatTheStatusDoes) {
  CpuWithAFlashController fixture{[](BusDriver& cpu) {
    cpu.Write32(kInterruptEnable, kDone);
    cpu.Write32(kCommand, kReadPage);
    cpu.WaitFor(sc_core::SC_ZERO_TIME);
    cpu.Write32(kStatus, 0);
  }};

  EXPECT_NO_THROW(fixture.platform.Run());

  EXPECT_TRUE(fixture.InterruptLine().line->read());
}

}  // namespace socpuppet
