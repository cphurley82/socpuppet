// The speed spike's harness (milestone M26): the host's core timed with
// the host's clock on three loops. Nothing here asserts anything about
// time. Each test asserts only that its program finished and that it ran
// by direct memory access, and prints one line of JSON for run.sh to keep:
//
//   [speed] {"loop": "counted", "seconds": 0.75, ...}
//
// See README.md here, and docs/speed-spike.md for what the lines became.

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <span>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/models/dbt_rise_cpu.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/speed/loops.h"
#include "tests/cpp/support/counting_probe.h"
#include "tests/cpp/support/riscv_program.h"

#ifndef SPEED_COMPILER
#define SPEED_COMPILER "unknown"
#endif

namespace {

// The host's core, the one with supervisor mode, behind a probe that
// counts transactions, with 256 KiB of RAM: the CPU tests' paging
// platform with room for the data pages.
struct SpeedPlatform {
  static constexpr std::uint64_t kRamBase = 0x8000'0000;
  static constexpr std::uint64_t kRamSize = 0x4'0000;
  static constexpr std::uint64_t kProgramPage = kRamBase;
  static constexpr std::uint64_t kFirstTable = kRamBase + 0x1000;
  static constexpr std::uint64_t kSecondTable = kRamBase + 0x2000;
  static constexpr std::uint64_t kThirdTable = kRamBase + 0x3000;
  static constexpr std::uint64_t kResultPage = kRamBase + 0x4000;
  // The data pages, which the walking loop loads from, in the RAM.
  static constexpr std::uint64_t kFirstDataPage = kRamBase + 0x8000;
  static constexpr std::uint64_t kDataPages = 32;
  // The top half of memory, where the third table maps 512 pages.
  static constexpr std::uint64_t kTopHalf = 0xFFFF'FFC0'0000'0000;
  static constexpr std::uint64_t kFirstDataAddress = kTopHalf + 0x2000;
  static constexpr std::uint64_t kCode =
      riscv::kPteRead | riscv::kPteExecute | riscv::kPteAccessed;
  static constexpr std::uint64_t kData = riscv::kPteRead | riscv::kPteWrite |
                                         riscv::kPteAccessed | riscv::kPteDirty;
  static constexpr riscv::Pages kPages{
      .root_table = kFirstTable, .code = kTopHalf, .result = kTopHalf + 0x1000};
  static constexpr speed::DataPages kDataLayout{.first = kFirstDataAddress,
                                                .pages = kDataPages};

  explicit SpeedPlatform(const sc_core::sc_time& quantum)
      : platform{WithAProbe()} {
    platform.SetQuantum(quantum);
    platform.Add("cpu", "dbt_rise_cpu",
                 {{"xlen", 64},
                  {"reset_vector", kRamBase},
                  {"floating_point", 1},
                  {"supervisor_mode", 1}});
    platform.Add("probe", "counting_probe");
    platform.Add("ram", "memory", {{"size", kRamSize}});
    platform.Add(
        "bus", "router",
        {{"outputs", 1}, {"out0.base", kRamBase}, {"out0.size", kRamSize}});
    platform.Bind("cpu.socket", "probe.target");
    platform.Bind("probe.initiator", "bus.target");
    platform.Bind("bus.out0", "ram.socket");
    platform.Elaborate();

    Put(kFirstTable + (256 * 8),
        riscv::PageTableEntry(kSecondTable, riscv::kPteValid));
    Put(kSecondTable, riscv::PageTableEntry(kThirdTable, riscv::kPteValid));
    Map(kPages.code, kProgramPage, kCode);
    Map(kPages.result, kResultPage, kData);
    for (std::uint64_t page = 0; page < kDataPages; ++page) {
      Map(kFirstDataAddress + (page * 0x1000), kFirstDataPage + (page * 0x1000),
          kData);
    }
  }

  static socpuppet::Registry WithAProbe() {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    registry.Add(
        "counting_probe", [](const char* name, socpuppet::Parameters&) {
          auto module = std::make_unique<CountingProbe>(name);
          std::vector<socpuppet::Port> ports{
              socpuppet::TargetPort("target", module->target),
              socpuppet::InitiatorPort("initiator", module->initiator)};
          return socpuppet::Instance{.module = std::move(module),
                                     .ports = std::move(ports)};
        });
    return registry;
  }

  void Map(std::uint64_t virtual_address, std::uint64_t physical,
           std::uint64_t bits) {
    Put(kThirdTable + (((virtual_address - kTopHalf) / 0x1000) * 8),
        riscv::PageTableEntry(physical, bits | riscv::kPteValid));
  }

  void Put(std::uint64_t physical, std::uint64_t value) {
    const auto bytes = socpuppet::LittleEndianBytes(value);
    platform.DebugWrite("cpu.socket", physical,
                        std::as_bytes(std::span{bytes}));
  }

  void Load(const riscv::Program& program) {
    platform.DebugWrite("cpu.socket", kProgramPage,
                        std::as_bytes(std::span{program}));
  }

  std::uint64_t Word(std::uint64_t physical) {
    std::array<std::uint8_t, 8> bytes{};
    platform.DebugRead("cpu.socket", physical,
                       std::as_writable_bytes(std::span{bytes}));
    return socpuppet::LoadLittleEndian<std::uint64_t>(bytes);
  }

  socpuppet::Platform platform;
};

std::string Environment(const char* name, const char* otherwise) {
  const char* value = std::getenv(name);  // NOLINT(concurrency-mt-unsafe)
  return value != nullptr ? value : otherwise;
}

// Runs `loop` to its result in slices of simulated time, timing the whole
// with the host's clock, and prints the line run.sh keeps.
void Measure(const std::string& name, const sc_core::sc_time& quantum,
             const speed::Loop& loop, std::uint64_t result_at) {
  SpeedPlatform speed{quantum};
  speed.Load(loop.program);

  // A slice is about a million instructions at the core's 100 ns each;
  // the last one overshoots into the core's sleep, which costs nothing.
  const sc_core::sc_time slice{100, sc_core::SC_MS};
  const sc_core::sc_time give_up{600, sc_core::SC_SEC};
  const auto start = std::chrono::steady_clock::now();
  while (speed.Word(result_at) == 0 && speed.platform.Time() < give_up) {
    speed.platform.Run(slice);
  }
  const std::chrono::duration<double> elapsed =
      std::chrono::steady_clock::now() - start;

  const std::uint64_t transactions =
      speed.platform.ModuleAt<CountingProbe>("probe").Transactions();
  ASSERT_NE(speed.Word(result_at), 0U) << "the loop did not finish";
  // Without direct access every fetch would be a transaction.
  EXPECT_LT(transactions, loop.instructions / 100)
      << "the CPU did not run by direct memory access";

  const double seconds = elapsed.count();
  std::ostringstream line;
  line.precision(6);
  line << "[speed] {"
       << R"("host": ")" << Environment("SPEED_HOST", "unknown") << R"(", )"
       << R"("env": ")" << Environment("SPEED_ENV", "unlabelled") << R"(", )"
       << R"("commit": ")" << Environment("SPEED_COMMIT", "unknown") << R"(", )"
       << R"("run": )" << Environment("SPEED_RUN", "0") << ", "
       << R"("cpu": "dbt-rise", )"
       << R"("backend": ")"
       << speed.platform.ModuleAt<socpuppet::DbtRiseCpu>("cpu").Backend()
       << R"(", )"
       << R"("compiler": ")" << SPEED_COMPILER << R"(", )"
       << R"("loop": ")" << name << R"(", )"
       << R"("quantum_us": )" << quantum.to_seconds() * 1e6 << ", "
       << R"("instructions": )" << loop.instructions << ", "
       << R"("walks": )" << loop.walks << ", "
       << R"("seconds": )" << seconds << ", "
       << R"("mips": )"
       << (static_cast<double>(loop.instructions) / seconds / 1e6) << ", "
       << R"("transactions": )" << transactions << ", "
       << R"("simulated_s": )" << speed.platform.Time().to_seconds() << "}";
  std::cout << line.str() << '\n' << std::flush;
}

const sc_core::sc_time kBoardsQuantum{100, sc_core::SC_US};
const sc_core::sc_time kM1sQuantum{1, sc_core::SC_MS};
constexpr riscv::Word kIterations = 1U << 24;
constexpr riscv::Word kRounds = 1U << 17;

}  // namespace

// At the quantum the Python boards run with.
TEST(Speed, Counted) {
  Measure("counted", kBoardsQuantum, speed::Counted(kIterations),
          SpeedPlatform::kProgramPage + riscv::kResultOffset);
}

// At the quantum M1's spike measured with, to set this beside its figure.
TEST(Speed, CountedAtM1sQuantum) {
  Measure("counted", kM1sQuantum, speed::Counted(kIterations),
          SpeedPlatform::kProgramPage + riscv::kResultOffset);
}

TEST(Speed, Walks) {
  Measure(
      "walks", kBoardsQuantum,
      speed::Paging(SpeedPlatform::kPages, SpeedPlatform::kDataLayout, kRounds,
                    /*empty_the_tlb=*/true),
      SpeedPlatform::kResultPage);
}

TEST(Speed, Hits) {
  Measure(
      "hits", kBoardsQuantum,
      speed::Paging(SpeedPlatform::kPages, SpeedPlatform::kDataLayout, kRounds,
                    /*empty_the_tlb=*/false),
      SpeedPlatform::kResultPage);
}
