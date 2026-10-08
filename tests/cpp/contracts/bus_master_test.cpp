#include <cstddef>
#include <cstdint>
#include <span>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/script.h"
#include "socpuppet/core/time.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/contracts/bus_master_contract.h"
#include "tests/cpp/support/riscv_program.h"

namespace {

// The stand-in: told what to do with a script.
struct ScriptedRig {
  using Contract = BusMasterContract<ScriptedRig>;

  static const char* Implementation() { return "scripted_bus_master"; }
  static socpuppet::Config Config() { return {}; }

  static void Load(socpuppet::Platform& platform, Behavior behavior) {
    auto& master = platform.ModuleAt<socpuppet::ScriptedBusMaster>("cpu");
    switch (behavior) {
      case Behavior::kWriteToTheProbe:
        master.SetScript([]() -> socpuppet::Script {
          co_await socpuppet::Write32(Contract::kProbeBase, 0);
        });
        break;
      case Behavior::kWriteToTheProbeTwice:
        master.SetScript([]() -> socpuppet::Script {
          co_await socpuppet::Write32(Contract::kProbeBase, 0);
          co_await socpuppet::Write32(Contract::kProbeBase, 0);
        });
        break;
      case Behavior::kWriteToTheProbeFourTimes:
        master.SetScript([]() -> socpuppet::Script {
          for (int count = 0; count < 4; ++count) {
            co_await socpuppet::Write32(Contract::kProbeBase, 0);
          }
        });
        break;
      case Behavior::kWaitForTheInterruptThenWriteToTheProbe:
        master.SetScript([]() -> socpuppet::Script {
          co_await socpuppet::WaitIrq{};
          co_await socpuppet::Write32(Contract::kProbeBase, 0);
        });
        break;
      case Behavior::kTakeInterruptsThroughThePlic:
        master.SetScript([]() -> socpuppet::Script {
          // The PLIC's registers for source 1: its priority, the enable
          // bits, and claim/complete.
          constexpr std::uint64_t kPriority1 = Contract::kPlicBase + 4;
          constexpr std::uint64_t kEnable = Contract::kPlicBase + 0x2000;
          constexpr std::uint64_t kClaimComplete =
              Contract::kPlicBase + 0x20'0004;
          co_await socpuppet::Write32(kPriority1, 1);
          co_await socpuppet::Write32(kEnable, 1 << 1);
          for (;;) {
            co_await socpuppet::WaitIrq{};
            const std::uint32_t claimed =
                co_await socpuppet::Read32(kClaimComplete);
            co_await socpuppet::Write32(Contract::kDeviceBase, 0);
            co_await socpuppet::Write32(kClaimComplete, claimed);
          }
        });
        break;
    }
  }
};

// The CPU: told what to do with a program in its RAM.
struct DbtRiseRig {
  using Contract = BusMasterContract<DbtRiseRig>;

  static const char* Implementation() { return "dbt_rise_cpu"; }
  static socpuppet::Config Config() {
    return {{"xlen", 64}, {"reset_vector", Contract::kProgramBase}};
  }

  static void Load(socpuppet::Platform& platform, Behavior behavior) {
    riscv::Program program;
    switch (behavior) {
      case Behavior::kWriteToTheProbe:
        program = riscv::StoreWordThenSleep(Contract::kProbeBase);
        break;
      case Behavior::kWriteToTheProbeTwice:
        program = riscv::StoreWordThenSleep(Contract::kProbeBase, /*times=*/2);
        break;
      case Behavior::kWriteToTheProbeFourTimes:
        program = riscv::StoreWordThenSleep(Contract::kProbeBase, /*times=*/4);
        break;
      case Behavior::kWaitForTheInterruptThenWriteToTheProbe:
        program = riscv::SleepUntilTheExternalInterruptThenStoreWord(
            Contract::kProbeBase);
        break;
      case Behavior::kTakeInterruptsThroughThePlic:
        program = riscv::HandleInterruptsThroughAPlic(Contract::kPlicBase,
                                                      Contract::kDeviceBase);
        break;
    }
    platform.DebugWrite("cpu.socket", Contract::kProgramBase,
                        std::as_bytes(std::span{program}));
  }
};

}  // namespace

INSTANTIATE_TYPED_TEST_SUITE_P(Scripted, BusMasterContract,
                               ::testing::Types<ScriptedRig>);
INSTANTIATE_TYPED_TEST_SUITE_P(DbtRise, BusMasterContract,
                               ::testing::Types<DbtRiseRig>);

// What follows is the scripted master's alone. A CPU model keeps its own
// time, and DBT-RISE's goes to sleep without letting the clock catch up
// (see docs/upstream.md).
class WhenAScriptEndsAheadOfTheClock : public BusMasterContract<ScriptedRig> {};

TEST_F(WhenAScriptEndsAheadOfTheClock, TheClockCatchesUpBeforeTheRunEnds) {
  const sc_core::sc_time latency = Microseconds(3);
  Build({.behavior = Behavior::kWriteToTheProbe,
         .probe_latency = latency,
         .quantum = Microseconds(50)});

  platform_->Run();

  EXPECT_EQ(platform_->Time(), latency);
}

class WhenAScriptWaitsWhileAheadOfTheClock
    : public BusMasterContract<ScriptedRig> {};

TEST_F(WhenAScriptWaitsWhileAheadOfTheClock,
       TheWaitStartsFromWhereTheScriptHadGotTo) {
  const sc_core::sc_time latency = Microseconds(3);
  Build({.behavior = Behavior::kWriteToTheProbe,
         .probe_latency = latency,
         .quantum = Microseconds(50)});
  platform_->ModuleAt<socpuppet::ScriptedBusMaster>("cpu").SetScript(
      []() -> socpuppet::Script {
        co_await socpuppet::Write32(kProbeBase, 0);
        co_await socpuppet::Wait{socpuppet::Picoseconds{7'000'000}};
        co_await socpuppet::Write32(kProbeBase, 0);
      });

  RunToTheEnd();

  ASSERT_THAT(probed_, ::testing::SizeIs(2));
  EXPECT_EQ(probed_.back().Time(), latency + Microseconds(7));
}
