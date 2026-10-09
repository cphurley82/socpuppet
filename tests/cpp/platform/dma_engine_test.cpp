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

// The engine's registers, each 32 bits wide, as docs/models/dma-engine.md
// gives them.
constexpr std::uint64_t kCommand = 0x00;
constexpr std::uint64_t kStatus = 0x04;
constexpr std::uint64_t kInterruptEnable = 0x08;
constexpr std::uint64_t kHostAddressLow = 0x0C;
constexpr std::uint64_t kHostAddressHigh = 0x10;
constexpr std::uint64_t kLocalAddress = 0x14;
constexpr std::uint64_t kLength = 0x18;

// What can be written to the command register.
constexpr std::uint32_t kFromHost = 1;
constexpr std::uint32_t kToHost = 2;

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;
constexpr std::uint32_t kBusy = 1U << 2;

// `length` bytes in which no two neighbours are the same.
std::vector<std::uint8_t> SomeBytes(std::size_t length) {
  std::vector<std::uint8_t> data(length);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(1 + index);
  }
  return data;
}

// A DMA engine between two memories of 256 bytes each, the host's and the
// SSD's own, each at address 0 of its side. A bus master is in the CPU's
// place, and a test has its eyes on the interrupt line. `body` is what the
// CPU does.
struct CpuWithADmaEngine {
  explicit CpuWithADmaEngine(const std::function<void(BusDriver&)>& body)
      : platform{WithADriverAndAWatcher(body)} {
    platform.Add("cpu", "bus_driver");
    platform.Add("dma", "dma_engine");
    platform.Add("host_memory", "memory", {{"size", 0x100}});
    platform.Add("local_memory", "memory", {{"size", 0x100}});
    platform.Add("watcher", "line_watcher");
    platform.Bind("cpu.socket", "dma.cpu");
    platform.Bind("dma.host", "host_memory.socket");
    platform.Bind("dma.local", "local_memory.socket");
    platform.Bind("dma.irq", "watcher.line");
    platform.Elaborate();
  }

  static Registry WithADriverAndAWatcher(
      const std::function<void(BusDriver&)>& body) {
    Registry registry = BuiltinComponents();
    AddBusDriver(registry, "bus_driver", body);
    AddLineWatcher(registry, "line_watcher");
    return registry;
  }

  // What a memory holds, and putting bytes there, the way a debugger
  // would. `side` is the engine's port the memory is on: "host" or "local".
  std::vector<std::uint8_t> MemoryAt(const std::string& side,
                                     std::uint64_t address,
                                     std::size_t length) {
    std::vector<std::uint8_t> data(length);
    platform.DebugRead("dma." + side, address,
                       std::as_writable_bytes(std::span{data}));
    return data;
  }
  void PutInMemory(const std::string& side, std::uint64_t address,
                   const std::vector<std::uint8_t>& data) {
    platform.DebugWrite("dma." + side, address, std::as_bytes(std::span{data}));
  }

  // A register as a debugger sees it, or nothing if the engine would not
  // show it. What comes back is not zeros unless the engine put them there.
  std::optional<std::uint32_t> DebugRead32(std::uint64_t offset) {
    std::array<std::uint8_t, 4> seen{0xA5, 0xA5, 0xA5, 0xA5};
    if (!platform.DebugRead("cpu.socket", offset,
                            std::as_writable_bytes(std::span{seen}))) {
      return std::nullopt;
    }
    return LoadLittleEndian<std::uint32_t>(seen);
  }

  // How many times the engine's interrupt line has risen, and whether it
  // is high now.
  int Rises() { return InterruptLine().Rises(); }
  bool LineIsHigh() { return InterruptLine().line->read(); }

  // Waits, in the calling simulation thread, for the line's first rise.
  // Nothing here takes simulated time, so the rise comes within delta
  // cycles: the patience is only there so that a line that never rises
  // fails the test and does not hang it.
  bool WaitForTheLineToRise() {
    return InterruptLine().WaitForRises(1, sc_core::sc_time(1, sc_core::SC_MS));
  }

  LineWatcher& InterruptLine() {
    return platform.ModuleAt<LineWatcher>("watcher");
  }

  Platform platform;
};

// Has the engine copy `length` bytes between `host_address` and
// `local_address`, and waits until it says it is no longer busy, the way
// firmware that polls would.
void Copy(BusDriver& cpu, std::uint32_t command, std::uint64_t host_address,
          std::uint32_t local_address, std::uint32_t length) {
  cpu.Write32(kHostAddressLow, static_cast<std::uint32_t>(host_address));
  cpu.Write32(kHostAddressHigh, static_cast<std::uint32_t>(host_address >> 32));
  cpu.Write32(kLocalAddress, local_address);
  cpu.Write32(kLength, length);
  cpu.Write32(kCommand, command);
  while ((cpu.Read32(kStatus) & kBusy) != 0) {
    cpu.WaitFor(sc_core::SC_ZERO_TIME);
  }
}

}  // namespace

TEST(WhenACpuHasADmaEngineCopyFromTheHostAndBackToAnotherPlace,
     TheBytesArriveThere) {
  CpuWithADmaEngine fixture{[](BusDriver& cpu) {
    Copy(cpu, kFromHost, 0x10, 0x40, 24);
    Copy(cpu, kToHost, 0x80, 0x40, 24);
  }};
  fixture.PutInMemory("host", 0x10, SomeBytes(24));

  fixture.platform.Run();

  EXPECT_EQ(fixture.MemoryAt("local", 0x40, 24), SomeBytes(24));
  EXPECT_EQ(fixture.MemoryAt("host", 0x80, 24), SomeBytes(24));
}

// The engine works alongside the CPU, not inside the CPU's write: when the
// write to the command register returns, nothing has been copied yet. The
// work is done in the next delta cycle, in which the CPU and the engine
// may run in either order, so the CPU gives it two.
TEST(WhenACpuHasJustToldADmaEngineToCopy,
     ItIsBusyWhenTheWriteReturnsAndDoneOnceItHasHadItsTurn) {
  std::uint32_t when_the_write_returned = 0;
  std::uint32_t afterwards = 0;
  CpuWithADmaEngine fixture{[&](BusDriver& cpu) {
    cpu.Write32(kLength, 24);
    cpu.Write32(kCommand, kFromHost);
    when_the_write_returned = cpu.Read32(kStatus);
    cpu.WaitFor(sc_core::SC_ZERO_TIME);
    cpu.WaitFor(sc_core::SC_ZERO_TIME);
    afterwards = cpu.Read32(kStatus);
  }};

  fixture.platform.Run();

  EXPECT_EQ(when_the_write_returned, kBusy);
  EXPECT_EQ(afterwards, kDone);
}

TEST(WhenADmaEngineFinishesACopyWithItsInterruptEnabled,
     ItsLineRisesAndStaysHigh) {
  CpuWithADmaEngine fixture{[](BusDriver& cpu) {
    cpu.Write32(kInterruptEnable, kDone);
    cpu.Write32(kLength, 24);
    cpu.Write32(kCommand, kFromHost);
  }};

  fixture.platform.Run();

  EXPECT_EQ(fixture.Rises(), 1);
  EXPECT_TRUE(fixture.LineIsHigh());
}

TEST(WhenTheCpuClearsTheStatusBitThatInterruptedIt, TheDmaEnginesLineFalls) {
  CpuWithADmaEngine* wired = nullptr;
  bool rose = false;
  CpuWithADmaEngine fixture{[&](BusDriver& cpu) {
    cpu.Write32(kInterruptEnable, kDone);
    cpu.Write32(kLength, 24);
    cpu.Write32(kCommand, kFromHost);
    rose = wired->WaitForTheLineToRise();
    cpu.Write32(kStatus, kDone);
  }};
  wired = &fixture;

  fixture.platform.Run();

  ASSERT_TRUE(rose);
  EXPECT_FALSE(fixture.LineIsHigh());
}

TEST(WhenADebuggerLooksAtADmaEnginesRegister, ItSeesWhatTheCpuWrote) {
  CpuWithADmaEngine fixture{[](BusDriver& cpu) { cpu.Write32(kLength, 24); }};
  fixture.platform.Run();

  EXPECT_EQ(fixture.DebugRead32(kLength), 24U);
}

TEST(WhenADebuggerWritesToADmaEnginesRegister, TheWriteIsDeclined) {
  const std::array<std::uint8_t, 4> some_length{24, 0, 0, 0};
  CpuWithADmaEngine fixture{[](BusDriver&) {}};

  const bool answered = fixture.platform.DebugWrite(
      "cpu.socket", kLength, std::as_bytes(std::span{some_length}));

  EXPECT_FALSE(answered);
  EXPECT_EQ(fixture.DebugRead32(kLength), 0U);
}

TEST(WhenADmaEngineRefusesAnAccess, TheCpuGetsAnAddressError) {
  tlm::tlm_response_status beside = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status too_narrow = tlm::TLM_INCOMPLETE_RESPONSE;
  CpuWithADmaEngine fixture{[&](BusDriver& cpu) {
    // 0x1C is after the last register.
    beside = cpu.Write32(0x1C, 1);
    too_narrow = cpu.Write(kLength, std::array<std::uint8_t, 2>{1, 0});
  }};

  fixture.platform.Run();

  EXPECT_EQ(beside, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(too_narrow, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

// Firmware may poll the status register and never look at the line.
TEST(WhenADmaEnginesInterruptLineIsLeftUnconnected,
     ThePlatformStillElaborates) {
  Platform platform{
      CpuWithADmaEngine::WithADriverAndAWatcher([](BusDriver&) {})};
  platform.Add("cpu", "bus_driver");
  platform.Add("dma", "dma_engine");
  platform.Add("host_memory", "memory", {{"size", 0x100}});
  platform.Add("local_memory", "memory", {{"size", 0x100}});
  platform.Bind("cpu.socket", "dma.cpu");
  platform.Bind("dma.host", "host_memory.socket");
  platform.Bind("dma.local", "local_memory.socket");

  EXPECT_NO_THROW(platform.Elaborate());
}

}  // namespace socpuppet
