#include "spikes/npu/doorbell.h"

#include <cstdint>
#include <functional>
#include <memory>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/npu/doorbell_module.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/test_components.h"

namespace spike {

namespace {

// The doorbell between a host and a programmable core, each a bus master
// with its hands on its own face of the block. 🎭 The core is a stand-in:
// it waits for the kick, as the Hexagon would wait for its interrupt, and
// writes COMPLETE, as the Hexagon's program would when its multiply is
// done.
struct HostAndCoreWithADoorbell {
  HostAndCoreWithADoorbell(const std::function<void(BusDriver&)>& host,
                           const std::function<void(BusDriver&)>& core)
      : platform{WithTheCast(host, core)} {
    platform.Add("host", "host");
    platform.Add("core", "core");
    platform.Add("doorbell", "doorbell");
    platform.Add("host_irq", "line_watcher");
    platform.Add("kick", "line_watcher");
    platform.Bind("host.socket", "doorbell.cpu");
    platform.Bind("core.socket", "doorbell.accelerator");
    platform.Bind("doorbell.irq", "host_irq.line");
    platform.Bind("doorbell.kick", "kick.line");
    platform.Elaborate();
  }

  static socpuppet::Registry WithTheCast(
      const std::function<void(BusDriver&)>& host,
      const std::function<void(BusDriver&)>& core) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    AddBusDriver(registry, "host", host);
    AddBusDriver(registry, "core", core);
    AddLineWatcher(registry, "line_watcher");
    registry.Add("doorbell", [](const char* name, socpuppet::Parameters&) {
      auto module = std::make_unique<Doorbell>(name);
      std::vector<socpuppet::Port> ports{
          socpuppet::TargetPort("cpu", module->cpu),
          socpuppet::TargetPort("accelerator", module->accelerator),
          socpuppet::WireSourcePort("irq", module->irq, /*required=*/false),
          socpuppet::WireSourcePort("kick", module->kick,
                                    /*required=*/false)};
      return socpuppet::Instance{.module = std::move(module),
                                 .ports = std::move(ports)};
    });
    return registry;
  }

  LineWatcher& Line(const char* which) {
    return platform.ModuleAt<LineWatcher>(which);
  }

  socpuppet::Platform platform;
};

TEST(WhenTheHostRingsTheDoorbellAndTheCoreCompletesTheWork,
     TheCoreWasKickedAndTheHostIsInterrupted) {
  std::uint32_t pending_as_the_core_saw_it = 0;
  std::uint64_t descriptor_as_the_core_saw_it = 0;
  std::uint32_t status_when_done = 0;
  HostAndCoreWithADoorbell* wired = nullptr;
  HostAndCoreWithADoorbell bench{
      [&](BusDriver& host) {
        host.Write32(kDoorbellInterruptEnable, kDoorbellStatusDone);
        host.Write32(kDoorbellDescriptorLow, 0x5000);
        host.Write32(kDoorbellDescriptorHigh, 1);
        host.Write32(kDoorbellCommand, kDoorbellCommandMatmul);
        wired->Line("host_irq")
            .WaitForRises(1, sc_core::sc_time(1, sc_core::SC_US));
        status_when_done = host.Read32(kDoorbellStatus);
      },
      [&](BusDriver& core) {
        wired->Line("kick").WaitForLevel(true,
                                         sc_core::sc_time(1, sc_core::SC_US));
        pending_as_the_core_saw_it = core.Read32(kDoorbellPending);
        descriptor_as_the_core_saw_it =
            core.Read32(kDoorbellDescriptorLow) |
            (std::uint64_t{core.Read32(kDoorbellDescriptorHigh)} << 32);
        core.Write32(kDoorbellComplete, kDoorbellCompleteDone);
      }};
  wired = &bench;

  bench.platform.Run();

  EXPECT_EQ(pending_as_the_core_saw_it, kDoorbellCommandMatmul);
  EXPECT_EQ(descriptor_as_the_core_saw_it, 0x1'0000'5000U);
  EXPECT_EQ(status_when_done, kDoorbellStatusDone);
  EXPECT_EQ(bench.Line("host_irq").Rises(), 1);
  EXPECT_FALSE(bench.Line("kick").line->read());
}

}  // namespace

}  // namespace spike
