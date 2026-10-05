#include <cstddef>
#include <cstdint>
#include <span>

#include <gtest/gtest.h>

#include "socpuppet/core/script.h"
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
