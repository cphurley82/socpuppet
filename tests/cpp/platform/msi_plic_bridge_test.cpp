#include <cstdint>
#include <functional>
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

}  // namespace socpuppet
