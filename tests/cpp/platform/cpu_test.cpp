#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/support/counting_probe.h"
#include "tests/cpp/support/interrupt_source.h"
#include "tests/cpp/support/recording_target.h"
#include "tests/cpp/support/riscv_program.h"
#include "tests/cpp/support/test_components.h"

using ::testing::AllOf;
using ::testing::HasSubstr;
using ::testing::ThrowsMessage;

namespace {

// A platform with a CPU and nothing else but a RAM for its program.
struct CpuPlatform {
  // Not zero, so that a CPU that ignored its reset vector would not pass.
  static constexpr std::uint64_t kResetVector = 0x100;

  // `more` is any parameters of the CPU beyond its word size and where it
  // starts.
  explicit CpuPlatform(std::uint64_t xlen, socpuppet::Config more = {}) {
    more.insert({{"xlen", xlen}, {"reset_vector", kResetVector}});
    platform.Add("cpu", "dbt_rise_cpu", more);
    platform.Add("ram", "memory", {{"size", 0x1000}});
    platform.Bind("cpu.socket", "ram.socket");
    platform.Elaborate();
  }

  // Puts `program` where the CPU starts executing.
  void Load(const riscv::Program& program) {
    platform.DebugWrite("cpu.socket", kResetVector,
                        std::as_bytes(std::span{program}));
  }

  // Runs long enough for any program here to finish and go to sleep. They
  // are a handful of instructions each. A millisecond is far more than
  // they need.
  void RunUntilAsleep() { platform.Run(sc_core::sc_time{1, sc_core::SC_MS}); }

  // The word a program run from the reset vector left as its result.
  std::uint32_t ResultWord() {
    std::array<std::uint8_t, 4> word{};
    platform.DebugRead("cpu.socket", kResetVector + riscv::kResultOffset,
                       std::as_writable_bytes(std::span{word}));
    return socpuppet::LoadLittleEndian<std::uint32_t>(word);
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

// The word that a program loaded at `start` left `offset` bytes into its
// result, read through the CPU's own view of memory.
std::uint32_t ResultWordOf(socpuppet::Platform& platform, std::uint64_t start,
                           std::uint64_t offset) {
  std::array<std::uint8_t, 4> word{};
  platform.DebugRead("cpu.socket", start + riscv::kResultOffset + offset,
                     std::as_writable_bytes(std::span{word}));
  return socpuppet::LoadLittleEndian<std::uint32_t>(word);
}

// The one core with supervisor mode is also the one with floating point.
// socpuppet offers the two together or neither, so both are asked for.
socpuppet::Config TheCoreWithSupervisorMode() {
  return {{"floating_point", 1}, {"supervisor_mode", 1}};
}

}  // namespace

TEST(WhenAPlatformWithACpuIsRun, TheCpuExecutesTheProgramAtItsResetVector) {
  CpuPlatform with_cpu{/*xlen=*/64};
  with_cpu.Load(riscv::StoreByteThenSleep(0x5A));

  with_cpu.RunUntilAsleep();

  EXPECT_EQ(with_cpu.Result(), 0x5A);
}

TEST(WhenXlenIs32, TheCpusRegistersAre32BitsWide) {
  CpuPlatform with_cpu{/*xlen=*/32};
  with_cpu.Load(riscv::StoreAllOnesShiftedRightThenSleep(28));

  with_cpu.RunUntilAsleep();

  // 32 ones shifted right by 28 leave 4 of them.
  EXPECT_EQ(with_cpu.Result(), 0b0000'1111);
}

TEST(WhenXlenIs64, TheCpusRegistersAre64BitsWide) {
  CpuPlatform with_cpu{/*xlen=*/64};
  with_cpu.Load(riscv::StoreAllOnesShiftedRightThenSleep(28));

  with_cpu.RunUntilAsleep();

  // 64 ones shifted right by 28 leave 36, so the low byte is full.
  EXPECT_EQ(with_cpu.Result(), 0b1111'1111);
}

TEST(WhenA64BitCpuHasFloatingPointAndSupervisorMode,
     AValueGoesThroughAFloatingPointRegisterAndComesBack) {
  CpuPlatform with_cpu{/*xlen=*/64, TheCoreWithSupervisorMode()};
  with_cpu.Load(riscv::MoveByteThroughAFloatingPointRegisterThenSleep(0x5A));

  with_cpu.RunUntilAsleep();

  EXPECT_EQ(with_cpu.Result(), 0x5A);
}

TEST(WhenXlenIsNeither32Nor64, TheCpuIsRefusedAndTheErrorNamesItAndTheChoices) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  EXPECT_THAT(
      [&] {
        platform.Add("cpu", "dbt_rise_cpu",
                     {{"xlen", 16}, {"reset_vector", 0}});
      },
      ThrowsMessage<std::invalid_argument>(
          AllOf(HasSubstr("16"), HasSubstr("32"), HasSubstr("64"))));
}

TEST(WhenACpuIsAskedForFloatingPointWithoutSupervisorMode,
     ItIsRefusedAndTheErrorNamesBoth) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  EXPECT_THAT(
      [&] {
        platform.Add(
            "cpu", "dbt_rise_cpu",
            {{"xlen", 64}, {"reset_vector", 0}, {"floating_point", 1}});
      },
      ThrowsMessage<std::invalid_argument>(
          AllOf(HasSubstr("floating_point"), HasSubstr("supervisor_mode"))));
}

TEST(WhenACpuIsAskedForSupervisorModeWithoutFloatingPoint,
     ItIsRefusedAndTheErrorNamesBoth) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  EXPECT_THAT(
      [&] {
        platform.Add(
            "cpu", "dbt_rise_cpu",
            {{"xlen", 64}, {"reset_vector", 0}, {"supervisor_mode", 1}});
      },
      ThrowsMessage<std::invalid_argument>(
          AllOf(HasSubstr("floating_point"), HasSubstr("supervisor_mode"))));
}

TEST(WhenA32BitCpuIsAskedForFloatingPointAndSupervisorMode,
     ItIsRefusedAndTheErrorSaysOnlyA64BitCpuHasThem) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  EXPECT_THAT(
      [&] {
        platform.Add("cpu", "dbt_rise_cpu",
                     {{"xlen", 32},
                      {"reset_vector", 0},
                      {"floating_point", 1},
                      {"supervisor_mode", 1}});
      },
      ThrowsMessage<std::invalid_argument>(
          AllOf(HasSubstr("floating_point"), HasSubstr("supervisor_mode"),
                HasSubstr("32"), HasSubstr("64"))));
}

// A platform whose CPU reaches its RAM through a probe that counts the
// transactions.
struct CpuPlatformWithAProbe {
  static constexpr std::uint64_t kResetVector = 0;

  CpuPlatformWithAProbe() : platform{WithAProbe()} {
    platform.Add("cpu", "dbt_rise_cpu",
                 {{"xlen", 64}, {"reset_vector", kResetVector}});
    platform.Add("probe", "counting_probe");
    platform.Add("ram", "memory", {{"size", 0x1000}});
    platform.Bind("cpu.socket", "probe.target");
    platform.Bind("probe.initiator", "ram.socket");
    platform.Elaborate();
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

  socpuppet::Platform platform;
};

TEST(WhenAMemoryOffersDirectAccess, TheCpuStopsUsingTheBusForIt) {
  CpuPlatformWithAProbe with_probe;
  const riscv::Word iterations = 4096;
  const riscv::Program program = riscv::CountDownThenSleep(iterations);
  with_probe.platform.DebugWrite("cpu.socket",
                                 CpuPlatformWithAProbe::kResetVector,
                                 std::as_bytes(std::span{program}));

  // Two instructions each time round, at 100 ns an instruction: under a
  // millisecond for the loop.
  with_probe.platform.Run(sc_core::sc_time{2, sc_core::SC_MS});

  // Without direct access, every instruction fetched is a transaction, so
  // there would be more than two per iteration.
  EXPECT_LT(with_probe.platform.ModuleAt<CountingProbe>("probe").Transactions(),
            iterations);
}

TEST(WhenAMemoryWithdrawsDirectAccess, TheCpuGoesBackToTheBus) {
  CpuPlatformWithAProbe with_probe;
  auto& probe = with_probe.platform.ModuleAt<CountingProbe>("probe");
  // A loop long enough to still be running at the end of the test: 13 ms.
  const riscv::Program program = riscv::CountDownThenSleep(65536);
  with_probe.platform.DebugWrite("cpu.socket",
                                 CpuPlatformWithAProbe::kResetVector,
                                 std::as_bytes(std::span{program}));
  with_probe.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});
  const std::uint64_t before = probe.Transactions();

  probe.WithdrawDirectAccess();
  with_probe.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  // A millisecond is 10,000 instructions, each now fetched over the bus.
  EXPECT_GE(probe.Transactions() - before, 10'000U);
}

TEST(WhenA64BitAndA32BitCpuShareASimulation, EachComputesInItsOwnWordSize) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  const riscv::Program program = riscv::StoreAllOnesShiftedRightThenSleep(28);
  for (const auto& [name, xlen] :
       {std::pair{"wide", 64}, std::pair{"narrow", 32}}) {
    const std::string cpu = std::string(name) + ".cpu";
    const std::string ram = std::string(name) + ".ram";
    platform.Add(
        cpu, "dbt_rise_cpu",
        {{"xlen", static_cast<std::uint64_t>(xlen)}, {"reset_vector", 0}});
    platform.Add(ram, "memory", {{"size", 0x1000}});
    platform.Bind(cpu + ".socket", ram + ".socket");
  }
  platform.Elaborate();
  for (const char* cpu : {"wide.cpu.socket", "narrow.cpu.socket"}) {
    platform.DebugWrite(cpu, 0, std::as_bytes(std::span{program}));
  }

  // Six instructions each.
  platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  std::byte wide{};
  std::byte narrow{};
  platform.DebugRead("wide.cpu.socket", riscv::kResultOffset,
                     std::span{&wide, 1});
  platform.DebugRead("narrow.cpu.socket", riscv::kResultOffset,
                     std::span{&narrow, 1});
  // What is left of 64 ones, and of 32, after a shift right by 28.
  EXPECT_EQ(std::to_integer<int>(wide), 0b1111'1111);
  EXPECT_EQ(std::to_integer<int>(narrow), 0b0000'1111);
}

// A platform with a CPU, a RAM for its program, and a device that
// interrupts it on the line `cpu_input` ("irq", "timer_irq" or
// "supervisor_irq").
struct CpuPlatformWithAnInterruptSource {
  static constexpr std::uint64_t kRamBase = 0x8000'0000;
  static constexpr std::uint64_t kDeviceBase = 0x1000'0000;

  // `more` is any parameters of the CPU beyond its word size and where it
  // starts.
  CpuPlatformWithAnInterruptSource(
      const std::string& cpu_input,
      const std::function<void(InterruptSource&)>& interrupts,
      socpuppet::Config more = {})
      : platform{WithAnInterruptSource(interrupts)} {
    more.insert({{"xlen", 64}, {"reset_vector", kRamBase}});
    platform.Add("cpu", "dbt_rise_cpu", more);
    platform.Add("bus", "router",
                 {{"outputs", 2},
                  {"out0.base", kRamBase},
                  {"out0.size", 0x1000},
                  {"out1.base", kDeviceBase},
                  {"out1.size", 0x100}});
    platform.Add("ram", "memory", {{"size", 0x1000}});
    platform.Add("device", "interrupt_source");
    platform.Bind("cpu.socket", "bus.target");
    platform.Bind("bus.out0", "ram.socket");
    platform.Bind("bus.out1", "device.socket");
    platform.Bind("device.line", "cpu." + cpu_input);
    platform.Elaborate();
  }

  void Load(const riscv::Program& program) {
    platform.DebugWrite("cpu.socket", kRamBase,
                        std::as_bytes(std::span{program}));
  }

  int TimesTheHandlerRan() {
    return platform.ModuleAt<InterruptSource>("device").TimesQuieted();
  }

  // The word a program left `offset` bytes into its result.
  std::uint32_t ResultWord(std::uint64_t offset) {
    return ResultWordOf(platform, kRamBase, offset);
  }

  static socpuppet::Registry WithAnInterruptSource(
      const std::function<void(InterruptSource&)>& interrupts) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    AddInterruptSource(registry, "interrupt_source", interrupts);
    return registry;
  }

  socpuppet::Platform platform;
};

TEST(WhenTheExternalInterruptLineRisesWhileTheCpuSleeps, ItsHandlerRuns) {
  CpuPlatformWithAnInterruptSource with_device{
      "irq", [](InterruptSource& device) {
        device.WaitFor(sc_core::sc_time{5, sc_core::SC_US});
        device.Raise();
      }};
  with_device.Load(riscv::HandleInterruptsByWritingTo(
      CpuPlatformWithAnInterruptSource::kDeviceBase,
      riscv::kMachineExternalInterrupt));

  // A dozen instructions before the interrupt and three after it.
  with_device.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_GE(with_device.TimesTheHandlerRan(), 1);
}

// Raises the line once a program has got to supervisor mode and gone to
// sleep: twenty instructions, at 100 ns each.
void RaiseOnceTheSupervisorSleeps(InterruptSource& device) {
  device.WaitFor(sc_core::sc_time{5, sc_core::SC_US});
  device.Raise();
}

// Long enough for any program here to have got to supervisor mode, taken
// its interrupt and gone back to sleep. They are a few dozen instructions.
const sc_core::sc_time kUntilTheSupervisorSleepsAgain{1, sc_core::SC_MS};

TEST(WhenAnInterruptHandedDownToSupervisorModeArrivesWhileTheCpuSleepsThere,
     TheSupervisorsHandlerRunsOnce) {
  CpuPlatformWithAnInterruptSource with_device{"supervisor_irq",
                                               RaiseOnceTheSupervisorSleeps,
                                               TheCoreWithSupervisorMode()};
  with_device.Load(riscv::HandleTheSupervisorExternalInterruptByWritingTo(
      CpuPlatformWithAnInterruptSource::kDeviceBase));

  with_device.platform.Run(kUntilTheSupervisorSleepsAgain);

  EXPECT_EQ(with_device.TimesTheHandlerRan(), 1);
}

TEST(WhenAnInterruptHandedDownToSupervisorModeArrivesWhileTheCpuSleepsThere,
     SupervisorModeSeesItEnabledAndPendingInItsOwnRegisters) {
  CpuPlatformWithAnInterruptSource with_device{"supervisor_irq",
                                               RaiseOnceTheSupervisorSleeps,
                                               TheCoreWithSupervisorMode()};
  with_device.Load(riscv::StoreSieThenSipOnTheSupervisorExternalInterrupt(
      CpuPlatformWithAnInterruptSource::kDeviceBase));

  with_device.platform.Run(kUntilTheSupervisorSleepsAgain);

  const std::uint32_t supervisor_external =
      1U << riscv::kSupervisorExternalInterrupt;
  const std::uint32_t sie = with_device.ResultWord(0);
  const std::uint32_t sip = with_device.ResultWord(4);
  EXPECT_EQ(sie, supervisor_external);
  EXPECT_EQ(sip, supervisor_external);
}

TEST(WhenSupervisorModeEnablesInterruptsThatWereNotHandedDownToIt,
     OnlyTheOneThatWasBecomesEnabled) {
  CpuPlatform with_cpu{/*xlen=*/64, TheCoreWithSupervisorMode()};
  with_cpu.Load(riscv::EnableEverySupervisorInterruptThenStoreSie());

  with_cpu.RunUntilAsleep();

  EXPECT_EQ(with_cpu.ResultWord(), 1U << riscv::kSupervisorExternalInterrupt);
}

TEST(WhenSupervisorModeSetsItsOwnSoftwareInterruptPending, ItsHandlerRunsOnce) {
  CpuPlatform with_cpu{/*xlen=*/64, TheCoreWithSupervisorMode()};
  with_cpu.Load(riscv::TakeASupervisorSoftwareInterruptOfItsOwnAsking());

  with_cpu.RunUntilAsleep();

  // The program's result is how many times its handler ran.
  EXPECT_EQ(with_cpu.ResultWord(), 1U);
}

TEST(WhenTheTimerInterruptLineRisesWhileTheCpuSleeps, ItsHandlerRuns) {
  CpuPlatformWithAnInterruptSource with_device{
      "timer_irq", [](InterruptSource& device) {
        device.WaitFor(sc_core::sc_time{5, sc_core::SC_US});
        device.Raise();
      }};
  with_device.Load(riscv::HandleInterruptsByWritingTo(
      CpuPlatformWithAnInterruptSource::kDeviceBase,
      riscv::kMachineTimerInterrupt));

  // A dozen instructions before the interrupt and three after it.
  with_device.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_GE(with_device.TimesTheHandlerRan(), 1);
}

TEST(WhenAHandlerQuietsTheDeviceThatInterrupted, ItRunsOncePerInterrupt) {
  CpuPlatformWithAnInterruptSource with_device{
      "irq", [](InterruptSource& device) {
        device.WaitFor(sc_core::sc_time{5, sc_core::SC_US});
        device.Raise();
        device.WaitFor(sc_core::sc_time{300, sc_core::SC_US});
        device.Raise();
      }};
  // With a quantum, the handler quiets the device and returns without the
  // rest of the platform getting a turn in between.
  with_device.platform.SetQuantum(sc_core::sc_time{100, sc_core::SC_US});
  with_device.Load(riscv::HandleInterruptsByWritingTo(
      CpuPlatformWithAnInterruptSource::kDeviceBase,
      riscv::kMachineExternalInterrupt));

  with_device.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_EQ(with_device.TimesTheHandlerRan(), 2);
}

TEST(WhenACpuAsksTheMachineTimerForAnInterrupt, ItComesOnceAndOnTime) {
  constexpr std::uint64_t kRamBase = 0x8000'0000;
  constexpr std::uint64_t kTimerBase = 0x0200'0000;
  constexpr std::uint64_t kProbeBase = 0x1000'0000;
  std::vector<RecordedAccess> probed;
  socpuppet::Registry registry = socpuppet::BuiltinComponents();
  AddRecordingTarget(registry, "probe", probed);
  socpuppet::Platform platform{std::move(registry)};
  // The CPU runs up to 100 us ahead of the clock that the timer counts by.
  const sc_core::sc_time quantum{100, sc_core::SC_US};
  platform.SetQuantum(quantum);
  platform.Add("cpu", "dbt_rise_cpu",
               {{"xlen", 64}, {"reset_vector", kRamBase}});
  platform.Add("bus", "router",
               {{"outputs", 3},
                {"out0.base", kRamBase},
                {"out0.size", 0x1000},
                {"out1.base", kTimerBase},
                {"out1.size", 0x1'0000},
                {"out2.base", kProbeBase},
                {"out2.size", 0x100}});
  platform.Add("ram", "memory", {{"size", 0x1000}});
  platform.Add("timer", "machine_timer", {{"frequency_hz", 10'000'000}});
  platform.Add("probe", "probe");
  platform.Bind("cpu.socket", "bus.target");
  platform.Bind("bus.out0", "ram.socket");
  platform.Bind("bus.out1", "timer.socket");
  platform.Bind("bus.out2", "probe.socket");
  platform.Bind("timer.irq", "cpu.timer_irq");
  platform.Elaborate();
  // 1,000 ticks at ten a microsecond: the interrupt is due at 100 us.
  const riscv::Program program =
      riscv::TakeOneTimerInterrupt(kTimerBase + 0x4000, 1000, kProbeBase);
  platform.DebugWrite("cpu.socket", kRamBase,
                      std::as_bytes(std::span{program}));

  platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  ASSERT_THAT(probed, ::testing::SizeIs(1));
  const sc_core::sc_time due{100, sc_core::SC_US};
  EXPECT_GE(probed.front().Time(), due);
  EXPECT_LE(probed.front().Time(), due + quantum);
}

// A platform with a CPU, a RAM for its program and a machine timer, whose
// count the CPU can read two ways: from the timer's register on the bus,
// and, if the two are connected, from its own `time` register.
struct CpuPlatformWithATimer {
  static constexpr std::uint64_t kRamBase = 0x8000'0000;
  static constexpr std::uint64_t kTimerBase = 0x0200'0000;
  // Where the timer has its count.
  static constexpr std::uint64_t kMtime = kTimerBase + 0xBFF8;

  CpuPlatformWithATimer(std::uint64_t xlen, bool time_is_connected) {
    // The CPU runs up to 100 us ahead of the clock that the timer counts
    // by.
    platform.SetQuantum(sc_core::sc_time{100, sc_core::SC_US});
    platform.Add("cpu", "dbt_rise_cpu",
                 {{"xlen", xlen}, {"reset_vector", kRamBase}});
    platform.Add("bus", "router",
                 {{"outputs", 2},
                  {"out0.base", kRamBase},
                  {"out0.size", 0x1000},
                  {"out1.base", kTimerBase},
                  {"out1.size", 0x1'0000}});
    platform.Add("ram", "memory", {{"size", 0x1000}});
    // The timer counts once for each instruction the CPU executes: both
    // go at 10 MHz.
    platform.Add("timer", "machine_timer", {{"frequency_hz", 10'000'000}});
    platform.Bind("cpu.socket", "bus.target");
    platform.Bind("bus.out0", "ram.socket");
    platform.Bind("bus.out1", "timer.socket");
    platform.Bind("timer.irq", "cpu.timer_irq");
    if (time_is_connected) platform.Bind("cpu.time", "timer.time");
    platform.Elaborate();
  }

  void Load(const riscv::Program& program) {
    platform.DebugWrite("cpu.socket", kRamBase,
                        std::as_bytes(std::span{program}));
  }

  // Any program here is asleep after 820 us.
  void RunUntilAsleep() { platform.Run(sc_core::sc_time{2, sc_core::SC_MS}); }

  // The word a program left `offset` bytes into its result.
  std::uint32_t ResultWord(std::uint64_t offset = 0) {
    return ResultWordOf(platform, kRamBase, offset);
  }

  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
};

// What reads the count both ways. Its loop is two instructions each time
// round, 819 us of them, so that the look comes eight quanta in and part of
// the way through a ninth, with the simulation's clock near 800 us and the
// CPU some 19 us ahead of it. A `time` that left the CPU's lead out, or
// counted the clock twice, would then show.
riscv::Program ReadTimeThenTheTimersOwnCount() {
  return riscv::ReadTimeThenTheTimersOwnCountThenSleep(
      CpuPlatformWithATimer::kMtime, /*iterations=*/4096);
}

TEST(WhenACpusTimeIsConnectedToItsTimer,
     TheTimeRegisterReadsOneTickBehindTheTimersOwnCountReadAnInstructionLater) {
  CpuPlatformWithATimer with_timer{/*xlen=*/64, /*time_is_connected=*/true};
  with_timer.Load(ReadTimeThenTheTimersOwnCount());

  with_timer.RunUntilAsleep();

  const std::uint32_t time = with_timer.ResultWord(0);
  const std::uint32_t the_timers_own_count = with_timer.ResultWord(4);
  EXPECT_EQ(time + 1, the_timers_own_count);
}

TEST(WhenACpusTimeIsNotConnected, TheTimeRegisterReadsZero) {
  CpuPlatformWithATimer with_timer{/*xlen=*/64, /*time_is_connected=*/false};
  with_timer.Load(ReadTimeThenTheTimersOwnCount());

  with_timer.RunUntilAsleep();

  const std::uint32_t time = with_timer.ResultWord(0);
  const std::uint32_t the_timers_own_count = with_timer.ResultWord(4);
  EXPECT_EQ(time, 0U);
  // The program did run, and the timer did count.
  EXPECT_GT(the_timers_own_count, 0U);
}

// A 32-bit CPU has the 64-bit count in two registers, `time` and `timeh`.
TEST(WhenA32BitCpusTimeIsConnectedToItsTimer,
     ItsTimehRegisterReadsTheUpperHalfOfTheCount) {
  CpuPlatformWithATimer with_timer{/*xlen=*/32, /*time_is_connected=*/true};
  // The upper half of a count that started at zero would take seven
  // minutes to be anything else, so the program writes it first.
  with_timer.Load(riscv::WriteTheUpperHalfOfTheTimersCountThenStoreTimeh(
      CpuPlatformWithATimer::kMtime, 0x5A));

  with_timer.RunUntilAsleep();

  EXPECT_EQ(with_timer.ResultWord(), 0x5AU);
}

TEST(WhenADeviceInterruptsACpuThroughThePlic, ItsHandlerRunsOncePerInterrupt) {
  constexpr std::uint64_t kRamBase = 0x8000'0000;
  constexpr std::uint64_t kPlicBase = 0x0C00'0000;
  constexpr std::uint64_t kDeviceBase = 0x1000'0000;
  socpuppet::Platform platform{
      CpuPlatformWithAnInterruptSource::WithAnInterruptSource(
          [](InterruptSource& device) {
            device.WaitFor(sc_core::sc_time{5, sc_core::SC_US});
            device.Raise();
            device.WaitFor(sc_core::sc_time{300, sc_core::SC_US});
            device.Raise();
          })};
  platform.SetQuantum(sc_core::sc_time{100, sc_core::SC_US});
  platform.Add("cpu", "dbt_rise_cpu",
               {{"xlen", 64}, {"reset_vector", kRamBase}});
  platform.Add("bus", "router",
               {{"outputs", 3},
                {"out0.base", kRamBase},
                {"out0.size", 0x1000},
                {"out1.base", kPlicBase},
                {"out1.size", 0x400'0000},
                {"out2.base", kDeviceBase},
                {"out2.size", 0x100}});
  platform.Add("ram", "memory", {{"size", 0x1000}});
  platform.Add("plic", "plic");
  platform.Add("device", "interrupt_source");
  platform.Bind("cpu.socket", "bus.target");
  platform.Bind("bus.out0", "ram.socket");
  platform.Bind("bus.out1", "plic.socket");
  platform.Bind("bus.out2", "device.socket");
  platform.Bind("device.line", "plic.source1");
  platform.Bind("plic.irq", "cpu.irq");
  platform.Elaborate();
  const riscv::Program program =
      riscv::HandleInterruptsThroughAPlic(kPlicBase, kDeviceBase);
  platform.DebugWrite("cpu.socket", kRamBase,
                      std::as_bytes(std::span{program}));

  platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_EQ(platform.ModuleAt<InterruptSource>("device").TimesQuieted(), 2);
}
