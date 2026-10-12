#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <ostream>
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
#include "tests/cpp/support/line_driver.h"
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

// A CPU whose reset line a test drives, with a RAM for its program, which
// it runs up to 100 us ahead of the clock.
struct CpuWithItsResetInATestsHands {
  static constexpr std::uint64_t kResetVector = 0x8000'0000;

  explicit CpuWithItsResetInATestsHands(const Drive& reset)
      : platform{WithALineDriver(reset)} {
    platform.SetQuantum(sc_core::sc_time{100, sc_core::SC_US});
    platform.Add("cpu", "dbt_rise_cpu",
                 {{"xlen", 64}, {"reset_vector", kResetVector}});
    platform.Add(
        "bus", "router",
        {{"outputs", 1}, {"out0.base", kResetVector}, {"out0.size", 0x1000}});
    platform.Add("ram", "memory", {{"size", 0x1000}});
    platform.Add("reset", "line_driver");
    platform.Bind("cpu.socket", "bus.target");
    platform.Bind("bus.out0", "ram.socket");
    platform.Bind("reset.line", "cpu.reset");
    platform.Elaborate();
  }

  static socpuppet::Registry WithALineDriver(const Drive& reset) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    AddLineDriver(registry, "line_driver", reset);
    return registry;
  }

  socpuppet::Platform platform;
};

// A reset is a pulse, and a real one is a few ticks of the clock long. A
// CPU model that is busy looks at its inputs once a quantum, so the whole
// pulse can come and go between two looks. It has still been reset. Here
// the looks are 100 us apart, and the pulse is 1 us long and comes at 250.
TEST(WhenAResetPulseComesAndGoesWhileABusyCpuIsAheadOfTheClock,
     TheCpuStartsOverAtItsResetVector) {
  CpuWithItsResetInATestsHands with_cpu{[](LineDriver& reset) {
    reset.WaitFor(sc_core::sc_time{250, sc_core::SC_US});
    reset.Set(true);
    reset.WaitFor(sc_core::sc_time{1, sc_core::SC_US});
    reset.Set(false);
  }};
  const riscv::Program program = riscv::CountStartsThen(/*sleep=*/false);
  with_cpu.platform.DebugWrite("cpu.socket",
                               CpuWithItsResetInATestsHands::kResetVector,
                               std::as_bytes(std::span{program}));

  with_cpu.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_EQ(ResultWordOf(with_cpu.platform,
                         CpuWithItsResetInATestsHands::kResetVector, 0),
            2U);
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

TEST(WhenAnInterruptArrivesAtALoadOnTheCoreWithSupervisorMode,
     TheLoadIsStillExecuted) {
  CpuPlatformWithAnInterruptSource with_device{
      "irq",
      [](InterruptSource& device) {
        // The program is asleep, waiting for this, after eight
        // instructions.
        device.WaitFor(sc_core::sc_time{5, sc_core::SC_US});
        device.Raise();
      },
      TheCoreWithSupervisorMode()};
  const riscv::Program program =
      riscv::TakeTheExternalInterruptAtALoadOfItsOwnFirstWord(
          CpuPlatformWithAnInterruptSource::kDeviceBase);
  with_device.Load(program);

  // A dozen instructions before the interrupt and six after it.
  with_device.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_EQ(with_device.ResultWord(0), program.front());
  // And the interrupt was taken, which is what made this a test of it.
  EXPECT_EQ(with_device.TimesTheHandlerRan(), 1);
}

// Raises the line once a program has got to supervisor mode and gone to
// sleep: twenty instructions, at 100 ns each.
void RaiseOnceTheSupervisorSleeps(InterruptSource& device) {
  device.WaitFor(sc_core::sc_time{5, sc_core::SC_US});
  device.Raise();
}

// Long enough for any program here to have got to supervisor mode, taken
// its interrupt and gone back to sleep. They are a few dozen instructions.
sc_core::sc_time UntilTheSupervisorSleepsAgain() { return {1, sc_core::SC_MS}; }

TEST(WhenAnInterruptHandedDownToSupervisorModeArrivesWhileTheCpuSleepsThere,
     TheSupervisorsHandlerRunsOnce) {
  CpuPlatformWithAnInterruptSource with_device{"supervisor_irq",
                                               RaiseOnceTheSupervisorSleeps,
                                               TheCoreWithSupervisorMode()};
  with_device.Load(riscv::HandleTheSupervisorExternalInterruptByWritingTo(
      CpuPlatformWithAnInterruptSource::kDeviceBase));

  with_device.platform.Run(UntilTheSupervisorSleepsAgain());

  EXPECT_EQ(with_device.TimesTheHandlerRan(), 1);
}

TEST(WhenAnInterruptHandedDownToSupervisorModeArrivesWhileTheCpuSleepsThere,
     SupervisorModeSeesItEnabledAndPendingInItsOwnRegisters) {
  CpuPlatformWithAnInterruptSource with_device{"supervisor_irq",
                                               RaiseOnceTheSupervisorSleeps,
                                               TheCoreWithSupervisorMode()};
  with_device.Load(riscv::StoreSieThenSipOnTheSupervisorExternalInterrupt(
      CpuPlatformWithAnInterruptSource::kDeviceBase));

  with_device.platform.Run(UntilTheSupervisorSleepsAgain());

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

// Raises the line once a program has enabled its interrupt and gone to
// sleep, which takes it four instructions at 100 ns each, and leaves the
// line high.
void RaiseOnceTheProgramSleeps(InterruptSource& device) {
  device.WaitFor(sc_core::sc_time{5, sc_core::SC_US});
  device.Raise();
}

// Zephyr clears an interrupt's bit in `mip` on its way into every handler.
// For the machine timer's interrupt that write does nothing on a real hart:
// the bit says what the line says, and is read-only. A core that lets the
// write through forgets an interrupt whose line then stays high, as the
// timer's does when the next compare value is already in the past.
TEST(WhenAProgramClearsTheTimerInterruptInMipWhileItsLineIsHigh,
     TheCoreWithSupervisorModeStillWakesToIt) {
  CpuPlatformWithAnInterruptSource with_device{
      "timer_irq", RaiseOnceTheProgramSleeps, TheCoreWithSupervisorMode()};
  with_device.Load(riscv::SleepClearTheInterruptInMipAndSleepAgainThenStoreOne(
      riscv::kMachineTimerInterrupt));

  // Four instructions before the line rises and four after it.
  with_device.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_EQ(with_device.ResultWord(0), 1U);
}

TEST(WhenAProgramClearsTheTimerInterruptInMipWhileItsLineIsHigh,
     TheCoreWithoutSupervisorModeStillWakesToIt) {
  CpuPlatformWithAnInterruptSource with_device{"timer_irq",
                                               RaiseOnceTheProgramSleeps};
  with_device.Load(riscv::SleepClearTheInterruptInMipAndSleepAgainThenStoreOne(
      riscv::kMachineTimerInterrupt));

  // Four instructions before the line rises and four after it.
  with_device.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_EQ(with_device.ResultWord(0), 1U);
}

// The external interrupt's bit is read-only in the same way: it says what
// the interrupt controller's line says. The line stays high after a claim
// when the controller has another interrupt waiting.
TEST(WhenAProgramClearsTheExternalInterruptInMipWhileItsLineIsHigh,
     TheCoreWithSupervisorModeStillWakesToIt) {
  CpuPlatformWithAnInterruptSource with_device{"irq", RaiseOnceTheProgramSleeps,
                                               TheCoreWithSupervisorMode()};
  with_device.Load(riscv::SleepClearTheInterruptInMipAndSleepAgainThenStoreOne(
      riscv::kMachineExternalInterrupt));

  // Four instructions before the line rises and four after it.
  with_device.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_EQ(with_device.ResultWord(0), 1U);
}

TEST(WhenAProgramClearsTheExternalInterruptInMipWhileItsLineIsHigh,
     TheCoreWithoutSupervisorModeStillWakesToIt) {
  CpuPlatformWithAnInterruptSource with_device{"irq",
                                               RaiseOnceTheProgramSleeps};
  with_device.Load(riscv::SleepClearTheInterruptInMipAndSleepAgainThenStoreOne(
      riscv::kMachineExternalInterrupt));

  // Four instructions before the line rises and four after it.
  with_device.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  EXPECT_EQ(with_device.ResultWord(0), 1U);
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
  // And the value it interrupts at.
  static constexpr std::uint64_t kMtimecmp = kTimerBase + 0x4000;

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

// Firmware reads the count, adds a wait to it and sets the compare value,
// so time that goes missing between the read and the write is a wait that
// ends late. The loop before is as in ReadTimeThenTheTimersOwnCount: it
// leaves the CPU some 19 us ahead of the simulation's clock.
TEST(WhenA32BitCpuAheadOfTheClockSetsItsCompareValueInThreeWrites,
     TheTimersCountMovesOnByFourInstructionsFromOneReadToTheNext) {
  CpuPlatformWithATimer with_timer{/*xlen=*/32, /*time_is_connected=*/false};
  with_timer.Load(
      riscv::ReadTheTimersCountEitherSideOfSettingItsCompareValueThenSleep(
          CpuPlatformWithATimer::kMtime, CpuPlatformWithATimer::kMtimecmp,
          /*iterations=*/4096, /*xlen=*/32));

  with_timer.RunUntilAsleep();

  const std::uint32_t before = with_timer.ResultWord(0);
  const std::uint32_t after = with_timer.ResultWord(4);
  // The three writes and a read: the timer counts once for each
  // instruction.
  EXPECT_EQ(after - before, 4U);
}

TEST(WhenA64BitCpuAheadOfTheClockSetsItsCompareValueInOneWrite,
     TheTimersCountMovesOnByTwoInstructionsFromOneReadToTheNext) {
  CpuPlatformWithATimer with_timer{/*xlen=*/64, /*time_is_connected=*/false};
  with_timer.Load(
      riscv::ReadTheTimersCountEitherSideOfSettingItsCompareValueThenSleep(
          CpuPlatformWithATimer::kMtime, CpuPlatformWithATimer::kMtimecmp,
          /*iterations=*/4096, /*xlen=*/64));

  with_timer.RunUntilAsleep();

  const std::uint32_t before = with_timer.ResultWord(0);
  const std::uint32_t after = with_timer.ResultWord(4);
  // The write and a read: the timer counts once for each instruction.
  EXPECT_EQ(after - before, 2U);
}

// What a test may ask of a CpuPlatformWithAnImsic.
struct ImsicPlatformSetup {
  // How far ahead of the simulation's clock the CPU may run.
  sc_core::sc_time quantum = sc_core::SC_ZERO_TIME;
  // Whether the device writes its message to the page for supervisor mode,
  // where otherwise it writes to machine mode's.
  bool to_the_supervisors_page = false;
  // The core's extras, as for TheCoreWithSupervisorMode.
  socpuppet::Config core = TheCoreWithSupervisorMode();
};

// A platform with a CPU, a RAM for its program, an IMSIC with its two
// pages for messages on the CPU's bus, one for machine mode and one for
// supervisor mode, and a device on that bus that sends one message. The
// CPU is the core the host has, which is the one that gets an IMSIC.
struct CpuPlatformWithAnImsic {
  static constexpr std::uint64_t kRamBase = 0x8000'0000;
  static constexpr std::uint64_t kMessagePage = 0x2400'0000;
  static constexpr std::uint64_t kSupervisorsMessagePage = 0x2800'0000;
  // The identity the device interrupts with.
  static constexpr std::uint32_t kIdentity = 5;

  explicit CpuPlatformWithAnImsic(const ImsicPlatformSetup& setup = {})
      : platform{WithADeviceThatSendsAMessageTo(setup.to_the_supervisors_page
                                                    ? kSupervisorsMessagePage
                                                    : kMessagePage)} {
    platform.SetQuantum(setup.quantum);
    socpuppet::Config cpu = setup.core;
    cpu.insert({{"xlen", 64}, {"reset_vector", kRamBase}});
    platform.Add("cpu", "dbt_rise_cpu", cpu);
    platform.Add("bus", "router",
                 {{"inputs", 2},
                  {"outputs", 3},
                  {"out0.base", kRamBase},
                  {"out0.size", 0x1000},
                  {"out1.base", kMessagePage},
                  {"out1.size", 0x1000},
                  {"out2.base", kSupervisorsMessagePage},
                  {"out2.size", 0x1000}});
    platform.Add("ram", "memory", {{"size", 0x1000}});
    platform.Add("imsic", "imsic", {{"identities", 63}});
    platform.Add("device", "device");
    platform.Bind("cpu.socket", "bus.target");
    platform.Bind("device.socket", "bus.in1");
    platform.Bind("bus.out0", "ram.socket");
    platform.Bind("bus.out1", "imsic.machine");
    platform.Bind("bus.out2", "imsic.supervisor");
    platform.Bind("imsic.irq", "cpu.irq");
    platform.Bind("imsic.supervisor_irq", "cpu.supervisor_irq");
    platform.Bind("cpu.csr", "imsic.csr");
    platform.Elaborate();
  }

  void Load(const riscv::Program& program) {
    platform.DebugWrite("cpu.socket", kRamBase,
                        std::as_bytes(std::span{program}));
  }

  // The message is sent at 5 us and a handler is a handful of
  // instructions, so any program here is asleep again long before 1 ms,
  // whatever the quantum.
  void RunUntilAsleep() { platform.Run(sc_core::sc_time{1, sc_core::SC_MS}); }

  // The word a program left `offset` bytes into its result.
  std::uint32_t ResultWord(std::uint64_t offset = 0) {
    return ResultWordOf(platform, kRamBase, offset);
  }

  static socpuppet::Registry WithADeviceThatSendsAMessageTo(
      std::uint64_t page) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    AddBusDriver(registry, "device", [page](BusDriver& device) {
      // Long enough for a program to have set itself up and gone to
      // sleep: three dozen instructions at the most, at 100 ns each.
      device.WaitFor(sc_core::sc_time{5, sc_core::SC_US});
      device.Write32(page, kIdentity);
    });
    return registry;
  }

  socpuppet::Platform platform;
};

TEST(WhenAMessageArrivesAtTheImsicOfACpuThatListensForItsIdentity,
     TheHandlerRunsOnceAndClaimsThatIdentity) {
  CpuPlatformWithAnImsic with_imsic;
  with_imsic.Load(
      riscv::HandleMessagesThroughAnImsic(CpuPlatformWithAnImsic::kIdentity));

  with_imsic.RunUntilAsleep();

  const std::uint32_t claimed = with_imsic.ResultWord(0);
  const std::uint32_t times_the_handler_ran = with_imsic.ResultWord(4);
  EXPECT_EQ(claimed, CpuPlatformWithAnImsic::kIdentity);
  EXPECT_EQ(times_the_handler_ran, 1U);
}

// A claim is what quiets an IMSIC, and the CPU hears that its line fell
// from a process that runs when the CPU's own lets it. With a quantum the
// CPU's does not, for a thousand instructions at a time, and the program's
// handler makes no bus access that would.
TEST(WhenAMessageArrivesAtTheImsicOfACpuThatRunsAheadOfTheClock,
     TheHandlerStillRunsOnce) {
  CpuPlatformWithAnImsic with_imsic{
      {.quantum = sc_core::sc_time{100, sc_core::SC_US}}};
  with_imsic.Load(
      riscv::HandleMessagesThroughAnImsic(CpuPlatformWithAnImsic::kIdentity));

  with_imsic.RunUntilAsleep();

  const std::uint32_t times_the_handler_ran = with_imsic.ResultWord(4);
  EXPECT_EQ(times_the_handler_ran, 1U);
}

// An operating system runs in supervisor mode, and its interrupts are
// messages to the IMSIC's page for that mode, which it switches on and
// claims from through supervisor mode's own three registers.
TEST(WhenAMessageArrivesAtTheSupervisorsPageOfTheImsicOfACpuThatListensThere,
     TheSupervisorsHandlerRunsOnceAndClaimsTheMessagesIdentity) {
  CpuPlatformWithAnImsic with_imsic{{.to_the_supervisors_page = true}};
  with_imsic.Load(riscv::HandleMessagesInSupervisorModeThroughAnImsic(
      CpuPlatformWithAnImsic::kIdentity));

  with_imsic.RunUntilAsleep();

  const std::uint32_t claimed = with_imsic.ResultWord(0);
  const std::uint32_t times_the_handler_ran = with_imsic.ResultWord(4);
  EXPECT_EQ(claimed, CpuPlatformWithAnImsic::kIdentity);
  EXPECT_EQ(times_the_handler_ran, 1U);
}

// As for machine mode's handler: the claim is all that gives the rest of
// the platform a turn before the supervisor's returns.
TEST(WhenAMessageArrivesAtTheSupervisorsPageOfACpuThatRunsAheadOfTheClock,
     TheSupervisorsHandlerStillRunsOnce) {
  CpuPlatformWithAnImsic with_imsic{
      {.quantum = sc_core::sc_time{100, sc_core::SC_US},
       .to_the_supervisors_page = true}};
  with_imsic.Load(riscv::HandleMessagesInSupervisorModeThroughAnImsic(
      CpuPlatformWithAnImsic::kIdentity));

  with_imsic.RunUntilAsleep();

  const std::uint32_t times_the_handler_ran = with_imsic.ResultWord(4);
  EXPECT_EQ(times_the_handler_ran, 1U);
}

// The two modes each select for themselves: an operating system that looks
// at a register of its file does not move what the monitor under it was
// looking at.
TEST(WhenACpuWithAnImsicSelectsARegisterForEachOfItsTwoModes,
     EachSelectionReadsBackAsItWasWritten) {
  CpuPlatformWithAnImsic with_imsic;
  with_imsic.Load(riscv::SelectForMachineModeThenForSupervisorModeAndStoreBoth(
      /*for_machine_mode=*/riscv::kEidelivery,
      /*for_supervisor_mode=*/riscv::kEie0));

  with_imsic.RunUntilAsleep();

  const std::uint32_t machine_modes = with_imsic.ResultWord(0);
  const std::uint32_t supervisor_modes = with_imsic.ResultWord(4);
  EXPECT_EQ(machine_modes, riscv::kEidelivery);
  EXPECT_EQ(supervisor_modes, riscv::kEie0);
}

// One of a hart's registers that are really its IMSIC's.
struct ImsicRegisterOfAHart {
  riscv::Word number;
  const char* name;
};

void PrintTo(const ImsicRegisterOfAHart& csr, std::ostream* out) {
  *out << csr.name;
}

// The registers are the IMSIC's, so a hart with none has not got them.
class WhenACpuWithNoImsicWritesARegisterAnImsicWouldAnswer
    : public ::testing::TestWithParam<ImsicRegisterOfAHart> {};

TEST_P(WhenACpuWithNoImsicWritesARegisterAnImsicWouldAnswer,
       ItTakesAnIllegalInstructionTrap) {
  CpuPlatform without_imsic{/*xlen=*/64, TheCoreWithSupervisorMode()};
  without_imsic.Load(riscv::StoreWhyWritingACsrTrapped(GetParam().number));

  without_imsic.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  EXPECT_EQ(without_imsic.ResultWord(), riscv::kIllegalInstruction + 1);
}

INSTANTIATE_TEST_SUITE_P(
    TheThreeOfEachMode, WhenACpuWithNoImsicWritesARegisterAnImsicWouldAnswer,
    ::testing::Values(ImsicRegisterOfAHart{riscv::kMiselect, "miselect"},
                      ImsicRegisterOfAHart{riscv::kMireg, "mireg"},
                      ImsicRegisterOfAHart{riscv::kMtopei, "mtopei"},
                      ImsicRegisterOfAHart{riscv::kSiselect, "siselect"},
                      ImsicRegisterOfAHart{riscv::kSireg, "sireg"},
                      ImsicRegisterOfAHart{riscv::kStopei, "stopei"}));

// The supervisor's three are a way to supervisor mode's file, and a hart
// with no such mode has no use for one: its IMSIC's second file is nobody's.
class WhenACpuWithAnImsicAndNoSupervisorModeWritesARegisterOfThatModes
    : public ::testing::TestWithParam<ImsicRegisterOfAHart> {};

TEST_P(WhenACpuWithAnImsicAndNoSupervisorModeWritesARegisterOfThatModes,
       ItTakesAnIllegalInstructionTrap) {
  CpuPlatformWithAnImsic with_imsic{{.core = {}}};
  with_imsic.Load(riscv::StoreWhyWritingACsrTrapped(GetParam().number));

  with_imsic.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  EXPECT_EQ(with_imsic.ResultWord(), riscv::kIllegalInstruction + 1);
}

INSTANTIATE_TEST_SUITE_P(
    TheThree, WhenACpuWithAnImsicAndNoSupervisorModeWritesARegisterOfThatModes,
    ::testing::Values(ImsicRegisterOfAHart{riscv::kSiselect, "siselect"},
                      ImsicRegisterOfAHart{riscv::kSireg, "sireg"},
                      ImsicRegisterOfAHart{riscv::kStopei, "stopei"}));

// An IMSIC's files can only be switched on through its hart.
TEST(WhenAnImsicsWayInForItsHartGoesNowhere,
     ElaborationIsRefusedAndTheErrorNamesThePort) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  platform.Add("cpu", "dbt_rise_cpu", {{"xlen", 64}, {"reset_vector", 0}});
  platform.Add("imsic", "imsic", {{"identities", 63}});
  platform.Bind("cpu.socket", "imsic.machine");
  platform.Bind("imsic.irq", "cpu.irq");

  EXPECT_THAT([&] { platform.Elaborate(); },
              ThrowsMessage<std::runtime_error>(HasSubstr("imsic.csr")));
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
