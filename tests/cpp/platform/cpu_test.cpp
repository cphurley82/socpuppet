#include <cstddef>
#include <cstdint>
#include <span>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "tests/cpp/support/riscv_program.h"

namespace {

// A platform with a CPU and nothing else but a RAM for its program.
struct CpuPlatform {
  // Not zero, so that a CPU that ignored its reset vector would not pass.
  static constexpr std::uint64_t kResetVector = 0x100;

  CpuPlatform() {
    platform.Add("cpu", "dbt_rise_cpu", {{"reset_vector", kResetVector}});
    platform.Add("ram", "memory", {{"size", 0x1000}});
    platform.Bind("cpu.socket", "ram.socket");
    platform.Elaborate();
  }

  // Puts `program` where the CPU starts executing.
  void Load(const riscv::Program& program) {
    platform.DebugWrite("cpu.socket", kResetVector,
                        std::as_bytes(std::span{program}));
  }

  // The byte a program run from the reset vector left as its result.
  std::uint8_t Result() {
    std::byte result{};
    platform.DebugRead("cpu.socket", kResetVector + riscv::kResultOffset,
                       std::span{&result, 1});
    return std::to_integer<std::uint8_t>(result);
  }

  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
};

}  // namespace

TEST(WhenAPlatformWithACpuIsRun, TheCpuExecutesTheProgramAtItsResetVector) {
  CpuPlatform with_cpu;
  with_cpu.Load(riscv::StoreByteThenSleep(0x5A));

  // The program is five instructions long. A millisecond is far more than
  // they need.
  with_cpu.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_EQ(with_cpu.Result(), 0x5A);
}
