#include <cstdint>

#include <gtest/gtest.h>

#include "socpuppet/core/script.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/platform.h"
#include "spikes/iss/cpu_slot.h"
#include "spikes/iss/harness/virt_board.h"

namespace spike {

// The stand-in fits the slot a real CPU model will fill.
static_assert(CpuSlot<socpuppet::ScriptedBusMaster>);

// The harness on its own, before any ISS exists: the scripted stand-in
// plays the CPU and does what a polled console driver does.
TEST(WhenTheScriptedStandInPrintsThroughTheUart, TheHarnessCapturesTheText) {
  socpuppet::Platform platform{SpikeComponents()};
  AddVirtBoard(platform, "board", "scripted_bus_master");
  platform.ModuleAt<socpuppet::ScriptedBusMaster>("board.cpu")
      .SetScript([]() -> socpuppet::Script {
        constexpr std::uint64_t kLineStatus = kUartBase + 5;
        constexpr std::uint32_t kTransmitterReady = 0x60;
        for (const char each : {'O', 'K', '\n'}) {
          co_await socpuppet::Expect32(kLineStatus, kTransmitterReady);
          co_await socpuppet::Write32(kUartBase,
                                      static_cast<std::uint32_t>(each));
        }
      });
  platform.Elaborate();

  platform.Run();

  EXPECT_EQ(UartOutput(platform, "board"), "OK\n");
}

}  // namespace spike
