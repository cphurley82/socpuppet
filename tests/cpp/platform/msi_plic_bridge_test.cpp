#include <array>
#include <cstdint>
#include <functional>
#include <span>
#include <string>

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

// A bus master wired straight to an MSI-to-PLIC bridge with two vectors,
// with a test's eyes on the line of each. `body` is what the master does.
struct MasterWithAnMsiPlicBridge {
  explicit MasterWithAnMsiPlicBridge(
      const std::function<void(BusDriver&)>& body)
      : platform{WithADriverAndAWatcher(body)} {
    platform.Add("driver", "bus_driver");
    platform.Add("bridge", "msi_plic_bridge", {{"vectors", 2}});
    platform.Add("watcher0", "line_watcher");
    platform.Add("watcher1", "line_watcher");
    platform.Bind("driver.socket", "bridge.socket");
    platform.Bind("bridge.irq0", "watcher0.line");
    platform.Bind("bridge.irq1", "watcher1.line");
    platform.Elaborate();
  }

  static Registry WithADriverAndAWatcher(
      const std::function<void(BusDriver&)>& body) {
    Registry registry = BuiltinComponents();
    AddBusDriver(registry, "bus_driver", body);
    AddLineWatcher(registry, "line_watcher");
    return registry;
  }

  // How many times the line of `vector` has risen.
  int Rises(unsigned vector) {
    return platform.ModuleAt<LineWatcher>("watcher" + std::to_string(vector))
        .Rises();
  }

  bool LineIsHigh(unsigned vector) {
    return platform.ModuleAt<LineWatcher>("watcher" + std::to_string(vector))
        .line->read();
  }

  // Waits, in the calling simulation thread, for the line of `vector` to
  // rise, and returns while it is high.
  void WaitForARise(unsigned vector) {
    sc_core::wait(
        platform.ModuleAt<LineWatcher>("watcher" + std::to_string(vector))
            .line.posedge_event());
  }

  Platform platform;
};

// An interrupt message: a 32-bit write whose data is the vector's number.
tlm::tlm_response_status SendMessage(BusDriver& bus, std::uint32_t vector) {
  return bus.Write32(0, vector);
}

}  // namespace

TEST(WhenAMessageArrivesAtAnMsiPlicBridge, TheLineOfItsVectorRisesAndNoOther) {
  MasterWithAnMsiPlicBridge fixture{
      [](BusDriver& bus) { SendMessage(bus, 1); }};

  fixture.platform.Run();

  EXPECT_EQ(fixture.Rises(1), 1);
  EXPECT_EQ(fixture.Rises(0), 0);
}

// Nothing ever tells the bridge that an interrupt was handled: the handler
// talks to the device and to the PLIC. A line left high would be a
// device that never stops asking.
TEST(WhenAnMsiPlicBridgeHasRaisedALine, TheLineFallsByItself) {
  MasterWithAnMsiPlicBridge fixture{
      [](BusDriver& bus) { SendMessage(bus, 1); }};

  fixture.platform.Run();

  EXPECT_FALSE(fixture.LineIsHigh(1));
}

// The second message arrives before the first has been put on the line,
// and the same holds for one that arrives while the line is still high. A
// PLIC hears a rise, so each message needs a fall before it.
TEST(WhenTwoMessagesForOneVectorArriveBackToBack, ItsLineRisesTwice) {
  MasterWithAnMsiPlicBridge fixture{[](BusDriver& bus) {
    SendMessage(bus, 1);
    SendMessage(bus, 1);
  }};

  fixture.platform.Run();

  EXPECT_EQ(fixture.Rises(1), 2);
}

// The rise that is on the line came before this message, so it does not
// speak for it. A PLIC hears a rise, and a rise needs a fall before it.
TEST(WhenAMessageReachesAnMsiPlicBridgeWhoseLineIsStillHigh,
     TheLineFallsAndRisesAgain) {
  MasterWithAnMsiPlicBridge* wired = nullptr;
  MasterWithAnMsiPlicBridge fixture{[&](BusDriver& bus) {
    SendMessage(bus, 1);
    wired->WaitForARise(1);
    SendMessage(bus, 1);
  }};
  wired = &fixture;

  fixture.platform.Run();

  EXPECT_EQ(fixture.Rises(1), 2);
}

TEST(WhenAMessageNamesAVectorAnMsiPlicBridgeHasNoLineFor, ItIsRefused) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  MasterWithAnMsiPlicBridge fixture{
      [&](BusDriver& bus) { response = SendMessage(bus, 2); }};

  fixture.platform.Run();

  EXPECT_EQ(response, tlm::TLM_GENERIC_ERROR_RESPONSE);
}

// A message is something sent, not something kept: there is nothing in
// the register to read back.
TEST(WhenAnMsiPlicBridgesRegisterIsRead, ItReadsZero) {
  std::array<std::uint8_t, 4> read{0xFF, 0xFF, 0xFF, 0xFF};
  MasterWithAnMsiPlicBridge fixture{[&](BusDriver& bus) { bus.Read(0, read); }};

  fixture.platform.Run();

  EXPECT_EQ(read, (std::array<std::uint8_t, 4>{0, 0, 0, 0}));
}

TEST(WhenAnMsiPlicBridgesRegisterIsRead, NoLineRises) {
  MasterWithAnMsiPlicBridge fixture{[](BusDriver& bus) { bus.Read32(0); }};

  fixture.platform.Run();

  EXPECT_EQ(fixture.Rises(0), 0);
  EXPECT_EQ(fixture.Rises(1), 0);
}

// A debugger that walks the address map looks at every register, and one
// that got no answer here would stop the walk.
TEST(WhenAnMsiPlicBridgesRegisterIsLookedAtByDebugAccess, ItIsSeenAsZero) {
  std::array<std::uint8_t, 4> seen{0xFF, 0xFF, 0xFF, 0xFF};
  MasterWithAnMsiPlicBridge fixture{[](BusDriver&) {}};

  fixture.platform.DebugRead("driver.socket", 0,
                             std::as_writable_bytes(std::span{seen}));

  EXPECT_EQ(seen, (std::array<std::uint8_t, 4>{0, 0, 0, 0}));
}

// A message is a bus access by a device. A debugger that could send one
// would interrupt the CPU it is there to look at.
TEST(WhenADebugAccessWritesToAnMsiPlicBridge, ItIsDeclined) {
  const std::array<std::uint8_t, 4> message{1, 0, 0, 0};
  MasterWithAnMsiPlicBridge fixture{[](BusDriver&) {}};

  const bool answered = fixture.platform.DebugWrite(
      "driver.socket", 0, std::as_bytes(std::span{message}));

  EXPECT_FALSE(answered);
}

TEST(WhenAnAccessToAnMsiPlicBridgeIsNot32BitsWide, ItGetsAnAddressError) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  MasterWithAnMsiPlicBridge fixture{[&](BusDriver& bus) {
    response = bus.Write(0, std::array<std::uint8_t, 2>{1, 0});
  }};

  fixture.platform.Run();

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

TEST(WhenAnAccessIsBesideAnMsiPlicBridgesRegister, ItGetsAnAddressError) {
  tlm::tlm_response_status response = tlm::TLM_INCOMPLETE_RESPONSE;
  MasterWithAnMsiPlicBridge fixture{
      [&](BusDriver& bus) { response = bus.Write32(4, 1); }};

  fixture.platform.Run();

  EXPECT_EQ(response, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

}  // namespace socpuppet
