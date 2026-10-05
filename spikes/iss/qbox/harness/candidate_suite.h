#ifndef SPIKES_ISS_QBOX_HARNESS_CANDIDATE_SUITE_H_
#define SPIKES_ISS_QBOX_HARNESS_CANDIDATE_SUITE_H_

#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "spikes/iss/qbox/harness/boot.h"
#include "spikes/iss/qbox/harness/rv_asm.h"
#include "spikes/iss/qbox/harness/virt_board.h"

// The steps of the spike's protocol that can be run, as tests. Every
// candidate is held to the same ones: its test program defines the three
// functions of Candidate and includes this header.
//
//   S2  two CPUs of different word sizes in one simulation
//   S3  a bare-metal smoke program: print, trap and return; reset
//   S4  Zephyr's hello_world for both word sizes
//   S5  direct memory access takes the RAM traffic off the bus
//   S6  speed
namespace spike {

struct Candidate {
  // What the report calls it.
  static const char* Name();
  // The registry name of its CPU. It takes the parameters `xlen` (32 or
  // 64) and `reset_pc`.
  static const char* Cpu();
  // SpikeComponents() plus that CPU.
  static socpuppet::Registry Components();
};

inline socpuppet::Config CpuConfig(std::uint64_t xlen) {
  return {{"xlen", xlen}, {"reset_pc", kRamBase}};
}

// A line in the test's output for the report to quote.
inline void Note(const std::string& what) {
  std::cout << "[ spike ] " << Candidate::Name() << ": " << what << "\n";
}

TEST(TheSmokeProgram, RunsOnBothWordSizesInOneSimulationAndSurvivesATrap) {
  SetQuantum(Milliseconds(1));
  socpuppet::Platform platform{Candidate::Components()};
  AddVirtBoard(platform, "rv64", Candidate::Cpu(), CpuConfig(64));
  AddVirtBoard(platform, "rv32", Candidate::Cpu(), CpuConfig(32));
  platform.Elaborate();
  Load(platform, "rv64", rv::SmokeProgram(kUartBase));
  Load(platform, "rv32", rv::SmokeProgram(kUartBase));

  RunUntil(
      platform,
      [&] {
        return UartOutput(platform, "rv64").ends_with("R\n") &&
               UartOutput(platform, "rv32").ends_with("R\n");
      },
      Milliseconds(20));

  EXPECT_EQ(UartOutput(platform, "rv64"), "OK\nTR\n");
  EXPECT_EQ(UartOutput(platform, "rv32"), "OK\nTR\n");
}

TEST(Sleep, WhenTheCpuIsAsleepARunWithNoTimeLimitReturns) {
#ifdef SPIKE_CPU_KEEPS_THE_KERNEL_WAITING
  GTEST_SKIP() << "A sleeping " << Candidate::Name()
               << " CPU has the kernel wait for the host, so a run with no "
               << "time limit would never return.";
#else
  SetQuantum(Milliseconds(1));
  socpuppet::Platform platform{Candidate::Components()};
  AddVirtBoard(platform, "board", Candidate::Cpu(), CpuConfig(64));
  platform.Elaborate();
  Load(platform, "board", rv::SmokeProgram(kUartBase));

  // The smoke program ends in `wfi`, and no interrupt will ever come.
  platform.Run();

  EXPECT_EQ(UartOutput(platform, "board"), "OK\nTR\n");
#endif
}

TEST(Reset, HoldsTheCpuWhileHighStartsItWhenReleasedAndRestartsItWhenRaised) {
  SetQuantum(Milliseconds(1));
  socpuppet::Platform platform{Candidate::Components()};
  AddVirtBoard(platform, "board", Candidate::Cpu(), CpuConfig(64));
  platform.Add("reset_driver", "line_driver", {{"initial", 1}});
  platform.Bind("reset_driver.line", "board.cpu.reset");
  // High from the start, released at 2 ms, raised at 6 ms, released at 8.
  platform.ModuleAt<LineDriver>("reset_driver")
      .FlipAt({Milliseconds(2), Milliseconds(6), Milliseconds(8)});
  platform.Elaborate();
  Load(platform, "board", rv::SmokeProgram(kUartBase));

  platform.Run(Milliseconds(1.5));
  const std::string while_held = UartOutput(platform, "board");
  platform.Run(Milliseconds(4));
  const std::string after_release = UartOutput(platform, "board");
  platform.Run(Milliseconds(6.5));
  const std::string after_second_release = UartOutput(platform, "board");

  EXPECT_EQ(while_held, "") << "the CPU ran while reset was high";
  EXPECT_EQ(after_release, "OK\nTR\n");
  EXPECT_EQ(after_second_release, "OK\nTR\nOK\nTR\n")
      << "raising reset again did not restart the CPU";
}

// Boots Zephyr's hello_world for the board named and checks its greeting.
inline void ZephyrHelloWorldPrintsItsGreeting(std::uint64_t xlen,
                                              const std::string& zephyr_board) {
  const std::string image =
      FirmwarePath("hello_world_" + zephyr_board + ".bin");
  if (!FileExists(image)) {
    // CI sets this, so that a missing image cannot pass for a boot.
    if (std::getenv("SPIKE_REQUIRE_FIRMWARE") != nullptr) {
      FAIL() << image << " is missing.";
    }
    GTEST_SKIP() << image << " is missing. Build it with "
                 << "firmware/build.sh.";
  }
  SetQuantum(Milliseconds(1));
  socpuppet::Platform platform{Candidate::Components()};
  AddVirtBoard(platform, "board", Candidate::Cpu(), CpuConfig(xlen));
  platform.Elaborate();
  Load(platform, "board", ReadFile(image));

  RunUntilPrinted(platform, "board", "Hello World! ", Milliseconds(2000));
  // Let the rest of the line come out.
  platform.Run(Milliseconds(5));

  EXPECT_THAT(UartOutput(platform, "board"),
              ::testing::HasSubstr("Hello World! " + zephyr_board));
  Note("Zephyr hello_world on " + zephyr_board + " printed its greeting by " +
       platform.Time().to_string() + " of simulated time");
}

TEST(ZephyrHelloWorld, PrintsItsGreetingOn64Bits) {
  ZephyrHelloWorldPrintsItsGreeting(64, "qemu_riscv64");
}

TEST(ZephyrHelloWorld, PrintsItsGreetingOn32Bits) {
  ZephyrHelloWorldPrintsItsGreeting(32, "qemu_riscv32");
}

TEST(DirectMemoryAccess, TakesTheRamTrafficOffTheBus) {
  constexpr rv::Word kIterations = 1U << 16;  // 131,072 instructions
  SetQuantum(Milliseconds(1));
  socpuppet::Platform platform{Candidate::Components()};
  AddVirtBoard(platform, "board", Candidate::Cpu(), CpuConfig(64));
  platform.Elaborate();
  Load(platform, "board", rv::CountdownProgram(kUartBase, kIterations));

  const bool finished =
      RunUntilPrinted(platform, "board", "D", Milliseconds(1000));

  const std::uint64_t transactions = RamProbe(platform, "board").Transactions();
  const std::uint64_t grants = RamProbe(platform, "board").DmiGrants();
  EXPECT_TRUE(finished);
  EXPECT_GE(grants, 1U) << "the CPU never asked for DMI";
  EXPECT_LT(transactions, 100U)
      << "the CPU kept fetching instructions over the bus";
  Note(std::to_string(2 * kIterations) + " instructions made " +
       std::to_string(transactions) + " RAM transactions and " +
       std::to_string(grants) + " DMI requests that were granted");
}

// Runs the countdown loop and reports instructions per second of real time.
inline void MeasureSpeed(std::uint64_t xlen, Dmi dmi, rv::Word iterations) {
  SetQuantum(Milliseconds(1));
  socpuppet::Platform platform{Candidate::Components()};
  AddVirtBoard(platform, "board", Candidate::Cpu(), CpuConfig(xlen), dmi);
  platform.Elaborate();
  Load(platform, "board", rv::CountdownProgram(kUartBase, iterations));

  const auto start = std::chrono::steady_clock::now();
  const bool finished = RunUntil(
      platform,
      [&] {
        return UartOutput(platform, "board").find('D') != std::string::npos;
      },
      sc_core::sc_time(600, sc_core::SC_SEC), Milliseconds(10));
  const std::chrono::duration<double> elapsed =
      std::chrono::steady_clock::now() - start;

  ASSERT_TRUE(finished);
  const double instructions = 2.0 * iterations;
  const double mips = instructions / elapsed.count() / 1e6;
  Note("RV" + std::to_string(xlen) +
       (dmi == Dmi::kOn ? ", DMI on: " : ", DMI off: ") + std::to_string(mips) +
       " million instructions per second (" +
       std::to_string(static_cast<std::uint64_t>(instructions)) +
       " instructions, finished at " + platform.Time().to_string() +
       " of simulated time)");
}

TEST(Speed, On64BitsWithDmi) { MeasureSpeed(64, Dmi::kOn, 1U << 24); }
TEST(Speed, On32BitsWithDmi) { MeasureSpeed(32, Dmi::kOn, 1U << 24); }
TEST(Speed, On64BitsWithoutDmi) { MeasureSpeed(64, Dmi::kOff, 1U << 20); }
TEST(Speed, On32BitsWithoutDmi) { MeasureSpeed(32, Dmi::kOff, 1U << 20); }

}  // namespace spike

#endif  // SPIKES_ISS_QBOX_HARNESS_CANDIDATE_SUITE_H_
