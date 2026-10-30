#include <array>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
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
#include "socpuppet/models/dbt_rise_cpu.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/support/counting_probe.h"
#include "tests/cpp/support/interrupt_source.h"
#include "tests/cpp/support/line_driver.h"
#include "tests/cpp/support/recording_target.h"
#include "tests/cpp/support/riscv_program.h"
#include "tests/cpp/support/test_components.h"
#include "tests/cpp/support/the_cpu.h"

using ::testing::AllOf;
using ::testing::HasSubstr;
using ::testing::ThrowsMessage;

namespace {

// The word that a program loaded at `start` left `offset` bytes into its
// result, read through the CPU's own view of memory.
std::uint32_t ResultWordOf(socpuppet::Platform& platform, std::uint64_t start,
                           std::uint64_t offset) {
  std::array<std::uint8_t, 4> word{};
  platform.DebugRead("cpu.socket", start + riscv::kResultOffset + offset,
                     std::as_writable_bytes(std::span{word}));
  return socpuppet::LoadLittleEndian<std::uint32_t>(word);
}

// A platform with a CPU and nothing else but a RAM for its program.
struct CpuPlatform {
  // Not zero, so that a CPU that ignored its reset vector would not pass.
  static constexpr std::uint64_t kResetVector = 0x100;

  // `more` is any parameters of the CPU beyond its word size and where it
  // starts.
  explicit CpuPlatform(std::uint64_t xlen, socpuppet::Config more = {}) {
    more.insert({{"xlen", xlen}, {"reset_vector", kResetVector}});
    AddTheCpu(platform, "cpu", more);
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

  // The word a program run from the reset vector left `offset` bytes into
  // its result.
  std::uint32_t ResultWord(std::uint64_t offset = 0) {
    return ResultWordOf(platform, kResetVector, offset);
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

// The one core with supervisor mode is also the one with floating point.
// socpuppet offers the two together or neither, so both are asked for.
socpuppet::Config TheCoreWithSupervisorMode() {
  return {{"floating_point", 1}, {"supervisor_mode", 1}};
}

// A parameterized case's name, from what its parameter's PrintTo says of
// it: "a swap, over the bus" is "ASwapOverTheBus". A name that says what
// the case is, rather than where it is in the list, is one a skip on QBox
// can name (tests/cpp/support/qbox_fates.h).
struct NamedByWhatItIs {
  template <typename Parameter>
  std::string operator()(
      const ::testing::TestParamInfo<Parameter>& info) const {
    std::string name;
    bool word_starts = true;
    for (const char letter : ::testing::PrintToString(info.param)) {
      if (std::isalnum(static_cast<unsigned char>(letter)) == 0) {
        word_starts = true;
        continue;
      }
      name += word_starts ? static_cast<char>(std::toupper(
                                static_cast<unsigned char>(letter)))
                          : letter;
      word_starts = false;
    }
    return name;
  }
};

}  // namespace

TEST(WhenAPlatformWithACpuIsRun, TheCpuExecutesTheProgramAtItsResetVector) {
  CpuPlatform with_cpu{/*xlen=*/64};
  with_cpu.Load(riscv::StoreByteThenSleep(0x5A));

  with_cpu.RunUntilAsleep();

  EXPECT_EQ(with_cpu.Result(), 0x5A);
}

// A disk's controller reads a program into a page of RAM that held another
// program, and the kernel executes fence.i before it runs it: the CPU must
// run what is there now. A CPU that keeps a translation of what it has
// executed cannot see such a write coming, since it is not the CPU's.
TEST(WhenSomethingElseWritesOverCodeAndTheProgramExecutesFenceI,
     TheProgramRunsWhatWasWritten) {
  constexpr std::int32_t kFunction = 0x40;
  const riscv::Word return_to_caller = riscv::Jalr(0, riscv::kRa, 0);
  CpuPlatform with_cpu{64};
  riscv::Program program{
      riscv::Auipc(riscv::kT0, 0),
      riscv::kFenceI,
      riscv::Jal(riscv::kRa, kFunction - 8),
      riscv::Sw(riscv::kT1, riscv::kT0, riscv::kResultOffset),
      riscv::Jal(0, -12),
  };
  program.resize(kFunction / sizeof(riscv::Word));
  program.push_back(riscv::Li(riscv::kT1, 1));
  program.push_back(return_to_caller);
  with_cpu.Load(program);
  with_cpu.RunUntilAsleep();
  const std::uint32_t before = with_cpu.ResultWord();

  const std::array<riscv::Word, 1> written_over{riscv::Li(riscv::kT1, 2)};
  with_cpu.platform.DebugWrite("cpu.socket",
                               CpuPlatform::kResetVector + kFunction,
                               std::as_bytes(std::span{written_over}));
  with_cpu.RunUntilAsleep();

  EXPECT_EQ(before, 1U);
  EXPECT_EQ(with_cpu.ResultWord(), 2U);
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

TEST(WhenACpuIsAskedForABackendItsBuildHasNoCoreFor,
     ItIsRefusedAndTheErrorNamesItAndTheOnesTheBuildHas) {
  const auto make_a_cpu_with_backend_spam = [] {
    // The extras are DbtRiseCpuExtras() and not {}: clang-tidy 23 takes the
    // comma after an empty {} for a trailing one (docs/upstream.md).
    const socpuppet::DbtRiseCpu cpu{"cpu",
                                    /*xlen=*/64,
                                    /*reset_vector=*/0,
                                    /*gdb_port=*/0,
                                    socpuppet::DbtRiseCpuExtras(),
                                    /*backend=*/"spam"};
  };

  EXPECT_THAT(make_a_cpu_with_backend_spam,
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr(R"("spam")"), HasSubstr(R"("interp")"))));
}

TEST(WhenNothingSaysWhichBackend,
     TheCoreWithSupervisorModeRunsWithTheBuildsDefault) {
  const socpuppet::DbtRiseCpu cpu{
      "cpu",
      /*xlen=*/64,
      /*reset_vector=*/0,
      /*gdb_port=*/0,
      {.floating_point = true, .supervisor_mode = true},
      /*backend=*/std::nullopt};

  EXPECT_EQ(cpu.Backend(), SOCPUPPET_DBT_RISE_DEFAULT_BACKEND);
}

// No translating backend has the cores with physical memory protection,
// so in a build whose default is one of them this is the fallback.
TEST(WhenNothingSaysWhichBackend, TheCoreWithMemoryProtectionRunsInterpreted) {
  const socpuppet::DbtRiseCpu cpu{"cpu",
                                  /*xlen=*/32,
                                  /*reset_vector=*/0,
                                  /*gdb_port=*/0,
                                  socpuppet::DbtRiseCpuExtras(),
                                  /*backend=*/std::nullopt};

  EXPECT_EQ(cpu.Backend(), "interp");
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
    AddTheCpu(platform, "cpu", {{"xlen", 64}, {"reset_vector", kResetVector}});
    platform.Add("probe", "counting_probe");
    platform.Add("ram", "memory", {{"size", 0x1000}});
    platform.Bind("cpu.socket", "probe.target");
    platform.Bind("probe.initiator", "ram.socket");
    platform.Elaborate();
  }

  static socpuppet::Registry WithAProbe() {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    registry.Add("counting_probe",
                 [](const char* name, socpuppet::Parameters&) {
                   auto module = std::make_unique<CountingProbe>(name);
                   std::vector<socpuppet::Port> ports{
                       socpuppet::TargetPort("target", module->target),
                       socpuppet::InitiatorPort("initiator", module->initiator),
                   };
                   return socpuppet::Instance{
                       .module = std::move(module),
                       .ports = std::move(ports),
                   };
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
    AddTheCpu(platform, "cpu", {{"xlen", 64}, {"reset_vector", kResetVector}});
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
    AddTheCpu(
        platform, cpu,
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
    AddTheCpu(platform, "cpu", more);
    platform.Add("bus", "router",
                 {
                     {"outputs", 2},
                     {"out0.base", kRamBase},
                     {"out0.size", 0x1000},
                     {"out1.base", kDeviceBase},
                     {"out1.size", 0x100},
                 });
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
// sleep: up to thirty instructions, at 100 ns each.
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

// Firmware with one mode calls its own kernel with `ecall` too, which is
// how Zephyr has a thread run something as if it were an interrupt, and a
// device can be asking when it does. The call's handler has to find its
// registers as the call left them, and not be entered a second time, by
// the interrupt, an instruction in.
TEST(WhenAnInterruptIsPendingAtACallOnTheCoreWithMachineModeOnly,
     TheHandlerTakesTheCallAsItWasMadeAndTheInterruptOnce) {
  CpuPlatformWithAnInterruptSource with_device{"irq",
                                               RaiseOnceTheProgramSleeps};
  with_device.Load(riscv::TakeAnInterruptAtAnEcallFromMachineMode(
      CpuPlatformWithAnInterruptSource::kDeviceBase));

  with_device.platform.Run(sc_core::sc_time{1, sc_core::SC_MS});

  // The program stores the cause with one added, and zero for no trap.
  const std::uint32_t why_the_handler_was_entered_for_the_call =
      with_device.ResultWord(0);
  const std::uint32_t where_it_was_to_return_to = with_device.ResultWord(4);
  const std::uint32_t where_the_call_is = with_device.ResultWord(8);
  const std::uint32_t the_program_ran_on = with_device.ResultWord(12);
  EXPECT_EQ(why_the_handler_was_entered_for_the_call,
            riscv::kEcallFromMachineMode + 1);
  EXPECT_EQ(where_it_was_to_return_to, where_the_call_is);
  EXPECT_EQ(with_device.TimesTheHandlerRan(), 1);
  EXPECT_EQ(the_program_ran_on, 1U);
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
  AddTheCpu(platform, "cpu", {{"xlen", 64}, {"reset_vector", kRamBase}});
  platform.Add("bus", "router",
               {
                   {"outputs", 3},
                   {"out0.base", kRamBase},
                   {"out0.size", 0x1000},
                   {"out1.base", kTimerBase},
                   {"out1.size", 0x1'0000},
                   {"out2.base", kProbeBase},
                   {"out2.size", 0x100},
               });
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

  // `more` is any parameters of the CPU beyond its word size and where it
  // starts.
  CpuPlatformWithATimer(std::uint64_t xlen, bool time_is_connected,
                        socpuppet::Config more = {}) {
    // The CPU runs up to 100 us ahead of the clock that the timer counts
    // by.
    platform.SetQuantum(sc_core::sc_time{100, sc_core::SC_US});
    more.insert({{"xlen", xlen}, {"reset_vector", kRamBase}});
    AddTheCpu(platform, "cpu", more);
    platform.Add("bus", "router",
                 {
                     {"outputs", 2},
                     {"out0.base", kRamBase},
                     {"out0.size", 0x1000},
                     {"out1.base", kTimerBase},
                     {"out1.size", 0x1'0000},
                 });
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

// What Linux's programs do for the time of day, with no call to the
// kernel: the kernel has allowed them the register, and the monitor has
// allowed the kernel.
TEST(WhenUserModeIsAllowedTheTimeRegisterOnACpuConnectedToItsTimer,
     ItReadsOneTickBehindTheTimersOwnCountAsMachineModeDoes) {
  CpuPlatformWithATimer with_timer{/*xlen=*/64, /*time_is_connected=*/true,
                                   TheCoreWithSupervisorMode()};
  with_timer.Load(riscv::ReadTimeThenTheTimersOwnCountThenSleep(
      CpuPlatformWithATimer::kMtime, /*iterations=*/4096,
      riscv::EnterUserModeAllowedToReadTime()));

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
    AddTheCpu(platform, "cpu", cpu);
    platform.Add("bus", "router",
                 {
                     {"inputs", 2},
                     {"outputs", 3},
                     {"out0.base", kRamBase},
                     {"out0.size", 0x1000},
                     {"out1.base", kMessagePage},
                     {"out1.size", 0x1000},
                     {"out2.base", kSupervisorsMessagePage},
                     {"out2.size", 0x1000},
                 });
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
  CpuPlatformWithAnImsic with_imsic{{
      .quantum = sc_core::sc_time{100, sc_core::SC_US},
      .to_the_supervisors_page = true,
  }};
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
                      ImsicRegisterOfAHart{riscv::kStopei, "stopei"}),
    NamedByWhatItIs{});

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
                      ImsicRegisterOfAHart{riscv::kStopei, "stopei"}),
    NamedByWhatItIs{});

// The hart has no Sstc, the extension that gives supervisor mode a timer
// compare of its own. Its timer is the machine timer's, which it asks
// machine mode for: OpenSBI's set_timer call writes `mtimecmp`.
TEST(WhenMachineModeWritesTheSupervisorsTimerCompare,
     ItTakesAnIllegalInstructionTrap) {
  CpuPlatform with_cpu{/*xlen=*/64, TheCoreWithSupervisorMode()};
  with_cpu.Load(riscv::StoreWhyWritingACsrTrapped(riscv::kStimecmp));

  with_cpu.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  EXPECT_EQ(with_cpu.ResultWord(), riscv::kIllegalInstruction + 1);
}

// An IMSIC's files can only be switched on through its hart.
TEST(WhenAnImsicsWayInForItsHartGoesNowhere,
     ElaborationIsRefusedAndTheErrorNamesThePort) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};
  AddTheCpu(platform, "cpu", {{"xlen", 64}, {"reset_vector", 0}});
  platform.Add("imsic", "imsic", {{"identities", 63}});
  platform.Bind("cpu.socket", "imsic.machine");
  platform.Bind("imsic.irq", "cpu.irq");

  EXPECT_THAT([&] { platform.Elaborate(); },
              ThrowsMessage<std::runtime_error>(HasSubstr("imsic.csr")));
}

// Interrupts that a program in machine mode, with interrupts off, hands
// down, enables and makes pending, and the one each mode would take next.
struct InterruptsOnTop {
  const char* name;
  riscv::Word handed_down;
  riscv::Word enabled;
  riscv::Word pending;
  // The number `mtopi` names, and the one `stopi` names: zero for none.
  riscv::Word machine_top;
  riscv::Word supervisor_top;
};

void PrintTo(const InterruptsOnTop& interrupts, std::ostream* out) {
  *out << interrupts.name;
}

// What a register that names a top interrupt says of it: its number, in
// bits 27 to 16. The priority in the bits below is the hart's own affair:
// OpenSBI and Linux read the number alone.
riscv::Word NumberIn(std::uint32_t top) {
  return (top >> riscv::kTopInterruptShift) & 0xFFFU;
}

// 🎓 Interrupts arrive at a hart as bits in `mip`, and more than one can be
// waiting. `mtopi` and `stopi` say which is the most urgent for each mode,
// so that a handler can ask instead of working it out from `mip`, `mie`
// and `mideleg` itself. OpenSBI's handler asks `mtopi` again and again
// until it reads zero, and Linux's asks `stopi`. The order among the six
// standard interrupts is fixed: external, then software, then timer, the
// machine's three before the supervisor's.
class WhenMachineModeMakesInterruptsPendingAndReadsWhichIsOnTop
    : public ::testing::TestWithParam<InterruptsOnTop> {};

TEST_P(WhenMachineModeMakesInterruptsPendingAndReadsWhichIsOnTop,
       MtopiAndStopiEachNameTheOneTheirModeWouldTakeNext) {
  const InterruptsOnTop& interrupts = GetParam();
  CpuPlatform with_cpu{/*xlen=*/64, TheCoreWithSupervisorMode()};
  with_cpu.Load(riscv::StoreTheTopInterrupts(
      interrupts.handed_down, interrupts.enabled, interrupts.pending));

  with_cpu.RunUntilAsleep();

  const std::uint32_t mtopi = with_cpu.ResultWord(0);
  const std::uint32_t stopi = with_cpu.ResultWord(4);
  const std::uint32_t trap_cause_plus_one = with_cpu.ResultWord(8);
  ASSERT_EQ(trap_cause_plus_one, 0U) << "A read trapped";
  EXPECT_EQ(NumberIn(mtopi), interrupts.machine_top);
  EXPECT_EQ(NumberIn(stopi), interrupts.supervisor_top);
}

constexpr riscv::Word kSoftware = 1U << riscv::kSupervisorSoftwareInterrupt;
constexpr riscv::Word kTimer = 1U << riscv::kSupervisorTimerInterrupt;
constexpr riscv::Word kExternal = 1U << riscv::kSupervisorExternalInterrupt;
constexpr riscv::Word kAllThree = kSoftware | kTimer | kExternal;

INSTANTIATE_TEST_SUITE_P(
    EachMixOfTheSupervisorsInterrupts,
    WhenMachineModeMakesInterruptsPendingAndReadsWhichIsOnTop,
    ::testing::Values(
        InterruptsOnTop{"the external interrupt, kept by machine mode", 0,
                        kExternal, kExternal,
                        riscv::kSupervisorExternalInterrupt, 0},
        InterruptsOnTop{"the external interrupt, handed down", kExternal,
                        kExternal, kExternal, 0,
                        riscv::kSupervisorExternalInterrupt},
        InterruptsOnTop{"the external interrupt, pending and not enabled", 0, 0,
                        kExternal, 0, 0},
        InterruptsOnTop{"all three, kept", 0, kAllThree, kAllThree,
                        riscv::kSupervisorExternalInterrupt, 0},
        InterruptsOnTop{"the software and timer interrupts, kept", 0,
                        kSoftware | kTimer, kSoftware | kTimer,
                        riscv::kSupervisorSoftwareInterrupt, 0},
        InterruptsOnTop{"all three, handed down", kAllThree, kAllThree,
                        kAllThree, 0, riscv::kSupervisorExternalInterrupt},
        InterruptsOnTop{
            "the timer interrupt handed down and the software one kept", kTimer,
            kSoftware | kTimer, kSoftware | kTimer,
            riscv::kSupervisorSoftwareInterrupt,
            riscv::kSupervisorTimerInterrupt}),
    NamedByWhatItIs{});

// A platform for a program that runs under paging: the core with
// supervisor mode, and 64 KiB of RAM with Sv39 page tables in it that a
// test adds pages to. The CPU reaches the RAM through a probe that counts
// the transactions, and a device on its bus can raise its supervisor
// external interrupt.
//
// 🎓 Sv39 translates an address in three steps, nine bits of it at a time:
// an entry of the first table leads to a second table, an entry of that to
// a third, and an entry of the third to the page. Addresses of 39 bits are
// two halves, the bottom of memory and the top, and an operating system's
// kernel lives in the top one, where no RAM is.
struct CpuPlatformWithPages {
  static constexpr std::uint64_t kRamBase = 0x8000'0000;
  // The RAM's pages, by what is in each.
  static constexpr std::uint64_t kProgramPage = kRamBase;
  static constexpr std::uint64_t kFirstTable = kRamBase + 0x1000;
  static constexpr std::uint64_t kSecondTable = kRamBase + 0x2000;
  static constexpr std::uint64_t kThirdTable = kRamBase + 0x3000;
  static constexpr std::uint64_t kResultPage = kRamBase + 0x4000;
  // Two pages for a test's own use, with one between that is nobody's, so
  // that they are not neighbours in the RAM.
  static constexpr std::uint64_t kFirstSparePage = kRamBase + 0x5000;
  static constexpr std::uint64_t kSecondSparePage = kRamBase + 0x7000;
  // The device that interrupts, which is not in the RAM. A write to it
  // quiets it.
  static constexpr std::uint64_t kDevice = 0x1000'0000;
  // The first address of the top half, which is where the tables here
  // lead: the 512 pages from it up are the third table's to map.
  static constexpr std::uint64_t kTopHalf = 0xFFFF'FFC0'0000'0000;
  // From here up nothing is mapped until a test maps it.
  static constexpr std::uint64_t kSpareAddresses = kTopHalf + 0x2000;
  // An address some way into the first page of those, for a test that
  // looks at the address a fault names: it is not the page's own.
  static constexpr std::uint64_t kInASparePage = kSpareAddresses + 0x18;
  // What a page of code is mapped with, and a page of data. Accessed, and
  // dirty where it is written: this hart takes a page fault at a page
  // that is not marked so, and marks none itself.
  static constexpr std::uint64_t kCode =
      riscv::kPteRead | riscv::kPteExecute | riscv::kPteAccessed;
  static constexpr std::uint64_t kData = riscv::kPteRead | riscv::kPteWrite |
                                         riscv::kPteAccessed | riscv::kPteDirty;
  // Where the program's page and the result's are mapped.
  static constexpr riscv::Pages kPages{
      .root_table = kFirstTable,
      .code = kTopHalf,
      .result = kTopHalf + 0x1000,
  };
  // The same for a program that leaves paging off: where the RAM has them.
  static constexpr riscv::Pages kWithPagingOff{
      .root_table = kFirstTable,
      .code = kProgramPage,
      .result = kResultPage,
  };

  // `interrupts` is what the device does. Left out, it never interrupts.
  explicit CpuPlatformWithPages(
      const std::function<void(InterruptSource&)>& interrupts =
          [](InterruptSource&) {})
      : platform{WithAProbeAndADeviceThat(interrupts)} {
    socpuppet::Config cpu = TheCoreWithSupervisorMode();
    cpu.insert({{"xlen", 64}, {"reset_vector", kRamBase}});
    AddTheCpu(platform, "cpu", cpu);
    platform.Add("bus", "router",
                 {
                     {"outputs", 2},
                     {"out0.base", kRamBase},
                     {"out0.size", 0x1'0000},
                     {"out1.base", kDevice},
                     {"out1.size", 0x1000},
                 });
    platform.Add("ram", "memory", {{"size", 0x1'0000}});
    platform.Add("probe", "counting_probe");
    platform.Add("device", "interrupt_source");
    platform.Bind("cpu.socket", "probe.target");
    platform.Bind("probe.initiator", "bus.target");
    platform.Bind("bus.out0", "ram.socket");
    platform.Bind("bus.out1", "device.socket");
    platform.Bind("device.line", "cpu.supervisor_irq");
    platform.Elaborate();

    // The way down to the third table: the top half starts at the first
    // table's entry 256, and its first 512 pages at the second's entry 0.
    WriteEntry(kFirstTable, 256,
               riscv::PageTableEntry(kSecondTable, riscv::kPteValid));
    WriteEntry(kSecondTable, 0,
               riscv::PageTableEntry(kThirdTable, riscv::kPteValid));
    Map(kPages.code, kProgramPage, kCode);
    Map(kPages.result, kResultPage, kData);
  }

  // The third table's entry for a page of RAM at `physical`, with what
  // `bits` allow there, and how far into that table the entry is for the
  // page at `virtual_address`, one of the 512 from kTopHalf up.
  static constexpr std::uint64_t EntryFor(std::uint64_t physical,
                                          std::uint64_t bits) {
    return riscv::PageTableEntry(physical, bits | riscv::kPteValid);
  }
  static constexpr std::uint64_t PlaceOfTheEntryOf(
      std::uint64_t virtual_address) {
    return ((virtual_address - kTopHalf) / 0x1000) * 8;
  }

  // Maps the page at `virtual_address` onto the page at `physical`.
  void Map(std::uint64_t virtual_address, std::uint64_t physical,
           std::uint64_t bits) {
    Put(kThirdTable + PlaceOfTheEntryOf(virtual_address),
        EntryFor(physical, bits));
  }

  // Maps the gigabyte the RAM is in onto itself, for code and for data,
  // with one entry of the first table: a page of 1 GiB. 🎓 An entry that
  // is a page can be in any of the three tables, and the higher the table
  // the bigger the page.
  void MapTheRamWhereItIs() {
    WriteEntry(
        kFirstTable, kRamBase >> 30U,
        riscv::PageTableEntry(kRamBase, kCode | kData | riscv::kPteValid));
  }

  // Puts `value` in the RAM at `physical`, in as many bytes as its type
  // has.
  template <typename Value>
  void Put(std::uint64_t physical, Value value) {
    const auto bytes = socpuppet::LittleEndianBytes(value);
    platform.DebugWrite("cpu.socket", physical,
                        std::as_bytes(std::span{bytes}));
  }

  // Puts `program` in the program's page, where the CPU starts, or in the
  // page of the RAM at `physical`.
  void Load(const riscv::Program& program,
            std::uint64_t physical = kProgramPage) {
    platform.DebugWrite("cpu.socket", physical,
                        std::as_bytes(std::span{program}));
  }

  // Any program here is asleep within a millisecond. Most are a few dozen
  // instructions, at 100 ns each, and the longest is a loop of some six
  // thousand.
  void RunUntilAsleep() { platform.Run(sc_core::sc_time{1, sc_core::SC_MS}); }

  int TimesTheHandlerRan() {
    return platform.ModuleAt<InterruptSource>("device").TimesQuieted();
  }

  // Has the RAM take back the direct access it gave and give no more, so
  // that the CPU reaches it by a transaction each time.
  void WithdrawDirectAccess() {
    platform.ModuleAt<CountingProbe>("probe").WithdrawDirectAccess();
  }

  // The word of 64 bits in the RAM at `physical`.
  std::uint64_t At(std::uint64_t physical) {
    std::array<std::uint8_t, 8> word{};
    platform.DebugRead("cpu.socket", physical,
                       std::as_writable_bytes(std::span{word}));
    return socpuppet::LoadLittleEndian<std::uint64_t>(word);
  }

  // How many transactions the CPU has sent to the bus.
  std::uint64_t Transactions() {
    return platform.ModuleAt<CountingProbe>("probe").Transactions();
  }

  // The word of 64 bits that a program left as its result, or the
  // `index`th of several, read where the RAM has it.
  std::uint64_t Result(std::uint64_t index = 0) {
    std::array<std::uint8_t, 8> word{};
    platform.DebugRead("cpu.socket", kResultPage + (index * 8),
                       std::as_writable_bytes(std::span{word}));
    return socpuppet::LoadLittleEndian<std::uint64_t>(word);
  }

  socpuppet::Platform platform;

 private:
  static socpuppet::Registry WithAProbeAndADeviceThat(
      const std::function<void(InterruptSource&)>& interrupts) {
    socpuppet::Registry registry = CpuPlatformWithAProbe::WithAProbe();
    AddInterruptSource(registry, "interrupt_source", interrupts);
    return registry;
  }

  void WriteEntry(std::uint64_t table, std::uint64_t index,
                  std::uint64_t entry) {
    Put(table + (index * 8), entry);
  }
};

// An operating system's kernel runs at addresses that no RAM is at, and
// its page tables say where each page of it really is. An instruction is
// found through them as a word of data is. Nothing here maps the program
// where it was loaded, so there is no other way for it to run.
static_assert(CpuPlatformWithPages::kPages.code !=
              CpuPlatformWithPages::kProgramPage);

TEST(WhenSupervisorModeIsEnteredAtAnAddressWithNoMemoryThatItsTablesMapOntoIt,
     TheProgramRunsThereAndStoresThroughItsTablesToo) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::StoreWhereItRunsInSupervisorModeUnderPaging(
      CpuPlatformWithPages::kPages));

  with_pages.RunUntilAsleep();

  const std::uint64_t page_it_ran_in = with_pages.Result() & ~0xFFFULL;
  EXPECT_EQ(page_it_ran_in, CpuPlatformWithPages::kPages.code);
}

// A kernel is entered with paging off and turns it on for itself. From the
// instruction after that it is running through its tables, at the
// addresses it was loaded at, until it jumps to the ones it was linked
// for. Linux maps itself where it is with big pages to get across.
TEST(WhenSupervisorModeTurnsPagingOnWithItsRamMappedWhereItIsByABigPage,
     ItRunsOnAndThenAtItsHighAddress) {
  // The result goes where the RAM has it, which is some way into the big
  // page: only the page's first 4 KiB are where any page would put them.
  constexpr riscv::Pages kWithTheResultWhereItIs{
      .root_table = CpuPlatformWithPages::kFirstTable,
      .code = CpuPlatformWithPages::kPages.code,
      .result = CpuPlatformWithPages::kResultPage,
  };
  CpuPlatformWithPages with_pages;
  with_pages.MapTheRamWhereItIs();
  with_pages.Load(riscv::TurnPagingOnInSupervisorModeThenStoreWhereItRuns(
      kWithTheResultWhereItIs));

  with_pages.RunUntilAsleep();

  const std::uint64_t page_it_ran_in = with_pages.Result() & ~0xFFFULL;
  EXPECT_EQ(page_it_ran_in, CpuPlatformWithPages::kPages.code);
}

// A way of using an address, by the instruction that does it with the
// address in t1, and the page fault it is.
struct UseOfAnAddress {
  const char* name;
  riscv::Word instruction;
  riscv::Word page_fault;
};

void PrintTo(const UseOfAnAddress& use, std::ostream* out) { *out << use.name; }

// A kernel maps a page when something first touches it, and the fault is
// how it hears: which kind of use, and of which address.
class WhenSupervisorModeUsesAnAddressNoPageIsMappedAt
    : public ::testing::TestWithParam<UseOfAnAddress> {};

TEST_P(WhenSupervisorModeUsesAnAddressNoPageIsMappedAt,
       ItTakesThePageFaultOfThatUseWhichSaysTheAddress) {
  constexpr std::uint64_t kNotMapped = CpuPlatformWithPages::kInASparePage;
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::StoreWhyAndWhereAccessesTrap(
      CpuPlatformWithPages::kPages, kNotMapped, {GetParam().instruction}));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why = with_pages.Result(0);
  const std::uint64_t where = with_pages.Result(1);
  EXPECT_EQ(why, GetParam().page_fault + 1);
  EXPECT_EQ(where, kNotMapped);
}

INSTANTIATE_TEST_SUITE_P(
    EachUse, WhenSupervisorModeUsesAnAddressNoPageIsMappedAt,
    ::testing::Values(
        UseOfAnAddress{"a load", riscv::Ld(riscv::kT0, riscv::kT1, 0),
                       riscv::kLoadPageFault},
        UseOfAnAddress{"a store", riscv::Sd(riscv::kT0, riscv::kT1, 0),
                       riscv::kStorePageFault},
        UseOfAnAddress{"a jump", riscv::Jalr(riscv::kZero, riscv::kT1, 0),
                       riscv::kInstructionPageFault}),
    NamedByWhatItIs{});

// A use supervisor mode makes of a page: what the page's entry says, and
// the instructions that use the page, with its address in t1.
struct UseOfAPage {
  const char* name;
  std::uint64_t bits;
  riscv::Program instructions;
  // The page fault it is, for a use that is one.
  riscv::Word page_fault = 0;
};

void PrintTo(const UseOfAPage& use, std::ostream* out) { *out << use.name; }

// 🎓 A page's entry says more than where the page is. Whether it has been
// used at all (accessed) and written (dirty), which a kernel reads to
// choose what to move out of memory and what to write back first. Whose it
// is. And what may be done there. This hart marks no page accessed or
// dirty itself: it takes a page fault at one that is not marked so, and
// leaves the marking to the kernel, which the specification allows and
// calls Svade.
class WhenSupervisorModeUsesAPageInAWayItsEntryDoesNotAllow
    : public ::testing::TestWithParam<UseOfAPage> {};

TEST_P(WhenSupervisorModeUsesAPageInAWayItsEntryDoesNotAllow,
       ItTakesThePageFaultOfThatUseWhichSaysTheAddress) {
  constexpr std::uint64_t kAddress = CpuPlatformWithPages::kInASparePage;
  CpuPlatformWithPages with_pages;
  with_pages.Map(CpuPlatformWithPages::kSpareAddresses,
                 CpuPlatformWithPages::kFirstSparePage, GetParam().bits);
  with_pages.Load(riscv::StoreWhyAndWhereAccessesTrap(
      CpuPlatformWithPages::kPages, kAddress, GetParam().instructions));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why = with_pages.Result(0);
  const std::uint64_t where = with_pages.Result(1);
  EXPECT_EQ(why, GetParam().page_fault + 1);
  EXPECT_EQ(where, kAddress);
}

constexpr riscv::Word kLoad = riscv::Ld(riscv::kT0, riscv::kT1, 0);
constexpr riscv::Word kStore = riscv::Sd(riscv::kT0, riscv::kT1, 0);

INSTANTIATE_TEST_SUITE_P(
    EachWay, WhenSupervisorModeUsesAPageInAWayItsEntryDoesNotAllow,
    ::testing::Values(UseOfAPage{"a load from a page not marked accessed",
                                 riscv::kPteRead | riscv::kPteWrite,
                                 {kLoad},
                                 riscv::kLoadPageFault},
                      UseOfAPage{"a store to a page not marked dirty",
                                 riscv::kPteRead | riscv::kPteWrite |
                                     riscv::kPteAccessed,
                                 {kStore},
                                 riscv::kStorePageFault},
                      UseOfAPage{"a load from a page of user mode's",
                                 CpuPlatformWithPages::kData | riscv::kPteUser,
                                 {kLoad},
                                 riscv::kLoadPageFault},
                      UseOfAPage{"a load from a page that may only be executed",
                                 riscv::kPteExecute | riscv::kPteAccessed,
                                 {kLoad},
                                 riscv::kLoadPageFault}),
    NamedByWhatItIs{});

// Supervisor mode's status register has a bit for each of two of those: a
// kernel sets SUM for as long as it copies to or from a program's memory,
// and MXR to read an instruction it has to emulate.
class WhenSupervisorModeSetsTheStatusBitThatAllowsAUseOfAPage
    : public ::testing::TestWithParam<UseOfAPage> {};

TEST_P(WhenSupervisorModeSetsTheStatusBitThatAllowsAUseOfAPage,
       TheUseIsMadeAndNothingTraps) {
  CpuPlatformWithPages with_pages;
  with_pages.Map(CpuPlatformWithPages::kSpareAddresses,
                 CpuPlatformWithPages::kFirstSparePage, GetParam().bits);
  with_pages.Load(riscv::StoreWhyAndWhereAccessesTrap(
      CpuPlatformWithPages::kPages, CpuPlatformWithPages::kSpareAddresses,
      GetParam().instructions));

  with_pages.RunUntilAsleep();

  const std::uint64_t every_instruction_ran = with_pages.Result(2);
  EXPECT_EQ(every_instruction_ran, 1U)
      << "It trapped, and the cause with one added is " << with_pages.Result(0);
}

INSTANTIATE_TEST_SUITE_P(
    EachBit, WhenSupervisorModeSetsTheStatusBitThatAllowsAUseOfAPage,
    ::testing::Values(
        UseOfAPage{
            "a load from a page of user mode's, with SUM",
            CpuPlatformWithPages::kData | riscv::kPteUser,
            {riscv::Lui(riscv::kT0, riscv::kSupervisorUserMemoryInUpper20),
             riscv::Csrs(riscv::kSstatus, riscv::kT0), kLoad}},
        UseOfAPage{
            "a load from a page that may only be executed, with MXR",
            riscv::kPteExecute | riscv::kPteAccessed,
            {riscv::Lui(riscv::kT0, riscv::kMakeExecutableReadableInUpper20),
             riscv::Csrs(riscv::kSstatus, riscv::kT0), kLoad}}),
    NamedByWhatItIs{});

// A hart keeps the translations it has worked out, so as not to walk the
// tables for every access, and what it keeps of a page that has only been
// read must not let a write by. A kernel that marks a page clean and
// counts on the fault to hear that it was written would otherwise never
// write it back.
TEST(WhenSupervisorModeStoresToAPageNotMarkedDirtyThatItHasJustLoadedFrom,
     TheStoreIsStillAPageFaultWhichSaysTheAddress) {
  constexpr std::uint64_t kAddress = CpuPlatformWithPages::kInASparePage;
  CpuPlatformWithPages with_pages;
  with_pages.Map(CpuPlatformWithPages::kSpareAddresses,
                 CpuPlatformWithPages::kFirstSparePage,
                 riscv::kPteRead | riscv::kPteWrite | riscv::kPteAccessed);
  with_pages.Load(riscv::StoreWhyAndWhereAccessesTrap(
      CpuPlatformWithPages::kPages, kAddress, {kLoad, kStore}));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why = with_pages.Result(0);
  const std::uint64_t where = with_pages.Result(1);
  EXPECT_EQ(why, riscv::kStorePageFault + 1);
  EXPECT_EQ(where, kAddress);
}

// A kernel moves a page by changing its entry, and a hart that keeps
// translations goes on using the old one until it is told to forget.
TEST(WhenAProgramChangesWhereAPageItHasUsedLeadsAndExecutesSfenceVma,
     ItsNextLoadIsFromWhereTheEntryNowLeads) {
  constexpr std::uint64_t kAddress = CpuPlatformWithPages::kSpareAddresses;
  // The third table itself, where the program can write it.
  constexpr std::uint64_t kTable = kAddress + 0x1000;
  constexpr std::uint64_t kInTheFirstPage = 0x1111'1111'1111'1111;
  constexpr std::uint64_t kInTheSecondPage = 0x2222'2222'2222'2222;
  CpuPlatformWithPages with_pages;
  with_pages.Map(kAddress, CpuPlatformWithPages::kFirstSparePage,
                 CpuPlatformWithPages::kData);
  with_pages.Map(kTable, CpuPlatformWithPages::kThirdTable,
                 CpuPlatformWithPages::kData);
  with_pages.Put(CpuPlatformWithPages::kFirstSparePage, kInTheFirstPage);
  with_pages.Put(CpuPlatformWithPages::kSecondSparePage, kInTheSecondPage);
  with_pages.Load(riscv::LoadChangeAnEntryAndLoadAgain(
      CpuPlatformWithPages::kPages, kAddress,
      kTable + CpuPlatformWithPages::PlaceOfTheEntryOf(kAddress),
      CpuPlatformWithPages::EntryFor(CpuPlatformWithPages::kSecondSparePage,
                                     CpuPlatformWithPages::kData)));

  with_pages.RunUntilAsleep();

  const std::uint64_t loaded_before = with_pages.Result(0);
  const std::uint64_t loaded_after = with_pages.Result(1);
  // The page did lead somewhere else at first, which is what makes the
  // second load a test of anything.
  EXPECT_EQ(loaded_before, kInTheFirstPage);
  EXPECT_EQ(loaded_after, kInTheSecondPage);
}

// A load from a page the hart has no translation for yet is several loads,
// from the page tables and then from the page. The core as borrowed
// dropped a load an interrupt arrived at, and a kernel's interrupts arrive
// at loads like this one all the time.
TEST(WhenAnInterruptArrivesAtALoadFromAPageTheHartHasNotUsedYet,
     TheLoadIsStillExecutedAndTheHandlerRunsOnce) {
  constexpr std::uint64_t kAddress = CpuPlatformWithPages::kSpareAddresses;
  constexpr std::uint64_t kDeviceAddress = kAddress + 0x1000;
  constexpr std::uint64_t kInThePage = 0x1234'5678'9ABC'DEF0;
  CpuPlatformWithPages with_pages{RaiseOnceTheSupervisorSleeps};
  with_pages.Map(kAddress, CpuPlatformWithPages::kFirstSparePage,
                 CpuPlatformWithPages::kData);
  with_pages.Map(kDeviceAddress, CpuPlatformWithPages::kDevice,
                 CpuPlatformWithPages::kData);
  with_pages.Put(CpuPlatformWithPages::kFirstSparePage, kInThePage);
  with_pages.Load(riscv::TakeAnInterruptAtALoadThatWalksThePageTables(
      CpuPlatformWithPages::kPages, kAddress, kDeviceAddress));

  with_pages.RunUntilAsleep();

  EXPECT_EQ(with_pages.Result(), kInThePage);
  EXPECT_EQ(with_pages.TimesTheHandlerRan(), 1);
}

// 🎓 A program asks its operating system for something with `ecall`, which
// is a trap on purpose. A monitor in machine mode hands that cause down,
// so that the operating system's handler takes it and not the monitor's.
TEST(WhenUserModeMakesASystemCallThatIsHandedDownToSupervisorMode,
     TheSupervisorsHandlerTakesItFromUserModeAndTheProgramRunsOn) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInUserMode(
      CpuPlatformWithPages::kWithPagingOff,
      /*delegated=*/std::uint64_t{1} << riscv::kEcallFromUserMode,
      {riscv::kEcall}));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why = with_pages.Result(0);
  const bool came_from_supervisor_mode =
      ((with_pages.Result(1) >> riscv::kSupervisorPreviousMode) & 1U) != 0;
  const std::uint64_t the_user_ran_on = with_pages.Result(2);
  EXPECT_EQ(why, riscv::kEcallFromUserMode + 1);
  EXPECT_FALSE(came_from_supervisor_mode);
  EXPECT_EQ(the_user_ran_on, 1U);
}

// What a monitor has not handed down is its own to see to.
TEST(WhenUserModeReadsARegisterOfSupervisorModesAndNothingIsHandedDown,
     MachineModeTakesAnIllegalInstructionTrap) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInUserMode(
      CpuPlatformWithPages::kWithPagingOff, /*delegated=*/0,
      {riscv::Csrr(riscv::kT0, riscv::kSstatus)}));

  with_pages.RunUntilAsleep();

  const std::uint64_t why_machine_mode_was_entered = with_pages.Result(3);
  EXPECT_EQ(why_machine_mode_was_entered, riscv::kIllegalInstruction + 1);
}

// An instruction, by a name for it.
struct NamedInstruction {
  const char* name;
  riscv::Word instruction;
};

void PrintTo(const NamedInstruction& named, std::ostream* out) {
  *out << named.name;
}

// A program is not its operating system: what belongs to the modes above
// it is not there for it. The returns from a trap are the ones that
// matter most, since each puts the hart in whatever mode a register says.
class WhenUserModeExecutesAnInstructionThatIsForTheModesAboveIt
    : public ::testing::TestWithParam<NamedInstruction> {};

TEST_P(WhenUserModeExecutesAnInstructionThatIsForTheModesAboveIt,
       ItIsAnIllegalInstructionWhichSupervisorModeTakesIfHandedDown) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInUserMode(
      CpuPlatformWithPages::kWithPagingOff,
      /*delegated=*/std::uint64_t{1} << riscv::kIllegalInstruction,
      {GetParam().instruction}));

  with_pages.RunUntilAsleep();

  const std::uint64_t why = with_pages.Result(0);
  EXPECT_EQ(why, riscv::kIllegalInstruction + 1);
}

INSTANTIATE_TEST_SUITE_P(
    EachOne, WhenUserModeExecutesAnInstructionThatIsForTheModesAboveIt,
    ::testing::Values(NamedInstruction{"a read of sstatus",
                                       riscv::Csrr(riscv::kT0,
                                                   riscv::kSstatus)},
                      NamedInstruction{"sfence.vma", riscv::kSfenceVma},
                      NamedInstruction{"sret", riscv::kSret},
                      NamedInstruction{"mret", riscv::kMret}),
    NamedByWhatItIs{});

// Something a program in user mode does with an address, and the page
// fault it is when the address is not the program's to use.
struct ActOfAUserProgram {
  const char* name;
  riscv::Program code;
  riscv::Word cause;
  std::uint64_t address;
};

void PrintTo(const ActOfAUserProgram& act, std::ostream* out) {
  *out << act.name;
}

// What Linux is, most of the time: a program in user mode on pages of its
// own, and a kernel on pages the program may not touch, which hears of the
// program only when it traps.
TEST(WhenAProgramInUserModeOnItsOwnPageUnderPagingMakesASystemCall,
     SupervisorModeTakesIt) {
  constexpr std::uint64_t kUsersPage = CpuPlatformWithPages::kSpareAddresses;
  CpuPlatformWithPages with_pages;
  with_pages.Map(kUsersPage, CpuPlatformWithPages::kFirstSparePage,
                 CpuPlatformWithPages::kCode | riscv::kPteUser);
  with_pages.Load({riscv::kEcall}, CpuPlatformWithPages::kFirstSparePage);
  with_pages.Load(riscv::RunTheCodeAtAnAddressInUserModeUnderPaging(
      CpuPlatformWithPages::kPages, kUsersPage));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why = with_pages.Result(0);
  EXPECT_EQ(why, riscv::kEcallFromUserMode + 1);
}

class WhenAProgramInUserModeOnItsOwnPageUnderPagingUsesAPageOfTheSupervisors
    : public ::testing::TestWithParam<ActOfAUserProgram> {};

TEST_P(WhenAProgramInUserModeOnItsOwnPageUnderPagingUsesAPageOfTheSupervisors,
       SupervisorModeTakesThePageFaultOfThatUseWhichSaysTheAddress) {
  constexpr std::uint64_t kUsersPage = CpuPlatformWithPages::kSpareAddresses;
  CpuPlatformWithPages with_pages;
  with_pages.Map(kUsersPage, CpuPlatformWithPages::kFirstSparePage,
                 CpuPlatformWithPages::kCode | riscv::kPteUser);
  with_pages.Load(GetParam().code, CpuPlatformWithPages::kFirstSparePage);
  with_pages.Load(riscv::RunTheCodeAtAnAddressInUserModeUnderPaging(
      CpuPlatformWithPages::kPages, kUsersPage));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why = with_pages.Result(0);
  const std::uint64_t where = with_pages.Result(1);
  EXPECT_EQ(why, GetParam().cause + 1);
  EXPECT_EQ(where, GetParam().address);
}

INSTANTIATE_TEST_SUITE_P(
    EachUse,
    WhenAProgramInUserModeOnItsOwnPageUnderPagingUsesAPageOfTheSupervisors,
    ::testing::Values(
        ActOfAUserProgram{"a load from it",
                          riscv::LoadFrom(CpuPlatformWithPages::kPages.result),
                          riscv::kLoadPageFault,
                          CpuPlatformWithPages::kPages.result},
        ActOfAUserProgram{
            "a jump into it", riscv::JumpTo(CpuPlatformWithPages::kPages.code),
            riscv::kInstructionPageFault, CpuPlatformWithPages::kPages.code}),
    NamedByWhatItIs{});

// A kernel calls the monitor under it with `ecall`, and one of the
// kernel's own interrupts can be pending when it does. Whichever a hart
// takes first, the monitor has to find its registers as the call left
// them: the kernel's interrupt is the kernel's to take, and never the
// monitor's, in the middle of its handler.
TEST(WhenASupervisorsInterruptIsPendingAtItsCallToMachineMode,
     MachineModeTakesTheCallAsItWasMadeAndSupervisorModeTheInterruptOnce) {
  CpuPlatformWithPages with_pages{RaiseOnceTheSupervisorSleeps};
  with_pages.Load(riscv::TakeAnInterruptAtAnEcallFromSupervisorMode(
      CpuPlatformWithPages::kWithPagingOff, CpuPlatformWithPages::kDevice));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why_machine_mode_was_entered = with_pages.Result(0);
  const std::uint64_t where_it_was_to_return_to = with_pages.Result(1);
  const std::uint64_t where_the_call_is = with_pages.Result(2);
  const std::uint64_t the_supervisor_ran_on = with_pages.Result(3);
  const int times_the_supervisor_took_its_interrupt =
      with_pages.TimesTheHandlerRan();
  EXPECT_EQ(why_machine_mode_was_entered, riscv::kEcallFromSupervisorMode + 1);
  EXPECT_EQ(where_it_was_to_return_to, where_the_call_is);
  EXPECT_EQ(times_the_supervisor_took_its_interrupt, 1);
  EXPECT_EQ(the_supervisor_ran_on, 1U);
}

// A monitor that wants to see every return an operating system makes sets
// TSR, and is then told of each `sret` as an illegal instruction.
TEST(WhenSupervisorModeExecutesSretWhileMachineModeHasItTrapped,
     MachineModeTakesAnIllegalInstructionTrap) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInSupervisorModeAfter(
      CpuPlatformWithPages::kWithPagingOff,
      riscv::SetInMstatus(riscv::kTrapSret), {riscv::kSret}));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why_machine_mode_was_entered = with_pages.Result(0);
  EXPECT_EQ(why_machine_mode_was_entered, riscv::kIllegalInstruction + 1);
}

// MPRV is for machine mode's use while it is in machine mode. Left set
// across a return to a mode below, it would be waiting the next time
// machine mode was entered, and the monitor's own loads and stores would
// go through the operating system's page tables.
TEST(WhenMachineModeReturnsToSupervisorModeWithMprvSet,
     MprvIsClearTheNextTimeMachineModeIsEntered) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInSupervisorModeAfter(
      CpuPlatformWithPages::kWithPagingOff,
      riscv::SetInMstatus(riscv::kModifyPrivilege), {riscv::kEcall}));

  with_pages.RunUntilAsleep();

  // Machine mode was entered again, by the call, which is what makes the
  // status it stored there the one to look at.
  const std::uint64_t why_machine_mode_was_entered = with_pages.Result(0);
  ASSERT_EQ(why_machine_mode_was_entered, riscv::kEcallFromSupervisorMode + 1);
  const bool mprv =
      ((with_pages.Result(1) >> riscv::kModifyPrivilege) & 1U) != 0;
  EXPECT_FALSE(mprv);
}

// A read of a counter from a mode below machine mode, and what the two
// registers that allow it say.
struct ReadOfACounter {
  const char* name;
  riscv::Word mode;
  riscv::Word counter;
  riscv::Word mcounteren;
  riscv::Word scounteren;
};

void PrintTo(const ReadOfACounter& read, std::ostream* out) {
  *out << read.name;
}

riscv::Program ProgramFor(const ReadOfACounter& read) {
  return riscv::ReadACounterIn(read.mode, CpuPlatformWithPages::kWithPagingOff,
                               read.counter, read.mcounteren, read.scounteren);
}

// Whether a read was let through, by a program of ProgramFor's that has
// run on a platform: it ran on, where a trap would have stopped it.
::testing::AssertionResult TheReadDidNotTrap(CpuPlatformWithPages& with_pages) {
  if (with_pages.Result(1) == 1) return ::testing::AssertionSuccess();
  return ::testing::AssertionFailure()
         << "The program did not run on, and the cause with one added, or "
            "zero for no trap, is "
         << with_pages.Result(0);
}

// 🎓 A hart counts its clock cycles and the instructions it has executed,
// and reads the time from its timer, and a program can read all three
// with no call to anyone: Linux gives its programs the time of day that
// way. Each mode says whether the one below it may. A monitor keeps them
// to itself if it wants a kernel to ask, and a kernel keeps them from a
// program it does not want timing things.
class WhenAModeBelowMachineModeReadsACounterItHasBeenAllowed
    : public ::testing::TestWithParam<ReadOfACounter> {};

TEST_P(WhenAModeBelowMachineModeReadsACounterItHasBeenAllowed,
       TheReadDoesNotTrapAndTheProgramRunsOn) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(ProgramFor(GetParam()));

  with_pages.RunUntilAsleep();

  EXPECT_TRUE(TheReadDidNotTrap(with_pages));
}

INSTANTIATE_TEST_SUITE_P(
    EachCounter, WhenAModeBelowMachineModeReadsACounterItHasBeenAllowed,
    ::testing::Values(
        ReadOfACounter{"supervisor mode, cycle", riscv::kSupervisorMode,
                       riscv::kCycle, riscv::kMayReadCycle, 0},
        ReadOfACounter{"supervisor mode, time", riscv::kSupervisorMode,
                       riscv::kTime, riscv::kMayReadTime, 0},
        ReadOfACounter{"supervisor mode, instret", riscv::kSupervisorMode,
                       riscv::kInstret, riscv::kMayReadInstret, 0},
        ReadOfACounter{"user mode, cycle", riscv::kUserMode, riscv::kCycle,
                       riscv::kMayReadCycle, riscv::kMayReadCycle},
        ReadOfACounter{"user mode, time", riscv::kUserMode, riscv::kTime,
                       riscv::kMayReadTime, riscv::kMayReadTime},
        ReadOfACounter{"user mode, instret", riscv::kUserMode, riscv::kInstret,
                       riscv::kMayReadInstret, riscv::kMayReadInstret}),
    NamedByWhatItIs{});

// Each row allows every counter but the one it reads, or allows that one
// in one register only, so that it is that bit which refuses it.
class WhenAModeBelowMachineModeReadsACounterItHasNotBeenAllowed
    : public ::testing::TestWithParam<ReadOfACounter> {};

TEST_P(WhenAModeBelowMachineModeReadsACounterItHasNotBeenAllowed,
       MachineModeTakesAnIllegalInstructionTrap) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(ProgramFor(GetParam()));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why_machine_mode_was_entered = with_pages.Result(0);
  EXPECT_EQ(why_machine_mode_was_entered, riscv::kIllegalInstruction + 1);
}

constexpr riscv::Word kMayReadAll =
    riscv::kMayReadCycle | riscv::kMayReadTime | riscv::kMayReadInstret;

INSTANTIATE_TEST_SUITE_P(
    EachCounter, WhenAModeBelowMachineModeReadsACounterItHasNotBeenAllowed,
    ::testing::Values(
        ReadOfACounter{"supervisor mode, cycle", riscv::kSupervisorMode,
                       riscv::kCycle, kMayReadAll & ~riscv::kMayReadCycle,
                       kMayReadAll},
        ReadOfACounter{"supervisor mode, time", riscv::kSupervisorMode,
                       riscv::kTime, kMayReadAll & ~riscv::kMayReadTime,
                       kMayReadAll},
        ReadOfACounter{"supervisor mode, instret", riscv::kSupervisorMode,
                       riscv::kInstret, kMayReadAll & ~riscv::kMayReadInstret,
                       kMayReadAll},
        ReadOfACounter{"user mode, time, which only machine mode allows",
                       riscv::kUserMode, riscv::kTime, kMayReadAll,
                       kMayReadAll & ~riscv::kMayReadTime},
        ReadOfACounter{"user mode, time, which only supervisor mode allows",
                       riscv::kUserMode, riscv::kTime,
                       kMayReadAll & ~riscv::kMayReadTime, kMayReadAll}),
    NamedByWhatItIs{});

// The registers are for the modes below machine mode, and say nothing of
// machine mode itself.
class WhenMachineModeReadsACounterThatNeitherRegisterAllows
    : public ::testing::TestWithParam<ReadOfACounter> {};

TEST_P(WhenMachineModeReadsACounterThatNeitherRegisterAllows,
       TheReadDoesNotTrapAndTheProgramRunsOn) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(ProgramFor(GetParam()));

  with_pages.RunUntilAsleep();

  EXPECT_TRUE(TheReadDidNotTrap(with_pages));
}

INSTANTIATE_TEST_SUITE_P(
    EachCounter, WhenMachineModeReadsACounterThatNeitherRegisterAllows,
    ::testing::Values(
        ReadOfACounter{"cycle", riscv::kMachineMode, riscv::kCycle, 0, 0},
        ReadOfACounter{"time", riscv::kMachineMode, riscv::kTime, 0, 0},
        ReadOfACounter{"instret", riscv::kMachineMode, riscv::kInstret, 0, 0}),
    NamedByWhatItIs{});

TEST(WhenMachineModeWritesTheTwoRegistersThatAllowCountersToBeRead,
     EachReadsBackAsItWasWritten) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::StoreWhatTheCounterEnablesReadAsAfterWriting(
      /*mcounteren=*/kMayReadAll, /*scounteren=*/riscv::kMayReadTime,
      CpuPlatformWithPages::kResultPage));

  with_pages.RunUntilAsleep();

  const std::uint64_t mcounteren = with_pages.Result(0);
  const std::uint64_t scounteren = with_pages.Result(1);
  EXPECT_EQ(mcounteren, kMayReadAll);
  EXPECT_EQ(scounteren, riscv::kMayReadTime);
}

// What a test puts together a program for supervisor mode from: lists of
// instructions, one after another.
riscv::Program Then(std::initializer_list<riscv::Program> parts) {
  riscv::Program all;
  for (const riscv::Program& part : parts) {
    all.insert(all.end(), part.begin(), part.end());
  }
  return all;
}

// Supervisor mode stores `sstatus` as the third word of its result, and
// calls machine mode, which stores `mstatus` as the second.
riscv::Program StoreSstatusThenCallMachineMode() {
  return {
      riscv::Csrr(riscv::kT0, riscv::kSstatus),
      riscv::Sd(riscv::kT0, riscv::kT2, 16),
      riscv::kEcall,
  };
}

// 🎓 `sstatus` is supervisor mode's view of `mstatus`: the same register,
// with what is machine mode's own left out. The state of the
// floating-point registers is in both, because it is the kernel that
// saves them for a program and has to switch them off and on.
TEST(WhenSupervisorModeSetsTheStateOfTheFloatingPointRegistersInSstatus,
     ItReadsBackThereAndInMstatus) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInSupervisorModeAfter(
      CpuPlatformWithPages::kWithPagingOff, {},
      Then({
          riscv::SetFloatingPointState(riscv::kSstatus,
                                       riscv::kFloatingPointClean),
          StoreSstatusThenCallMachineMode(),
      })));

  with_pages.RunUntilAsleep();

  const std::uint64_t mstatus = with_pages.Result(1);
  const std::uint64_t sstatus = with_pages.Result(2);
  EXPECT_EQ(riscv::FloatingPointStateIn(sstatus), riscv::kFloatingPointClean);
  EXPECT_EQ(riscv::FloatingPointStateIn(mstatus), riscv::kFloatingPointClean);
}

// 🎓 A kernel may leave floating point off for a program until the program
// first uses it, as Zephyr does. The trap is how it hears, and what lets
// it not save and restore thirty-two registers for every program that
// never does. It then switches floating point on and returns to the same
// instruction, so the trap has to say where that was.
class WhenFloatingPointIsOffAndSupervisorModeUsesIt
    : public ::testing::TestWithParam<NamedInstruction> {};

TEST_P(WhenFloatingPointIsOffAndSupervisorModeUsesIt,
       MachineModeTakesAnIllegalInstructionTrapAtThatInstruction) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInSupervisorModeAfter(
      CpuPlatformWithPages::kWithPagingOff, {}, {GetParam().instruction}));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why_machine_mode_was_entered = with_pages.Result(0);
  const std::uint64_t how_far_past_it_the_trap_returns = with_pages.Result(3);
  EXPECT_EQ(why_machine_mode_was_entered, riscv::kIllegalInstruction + 1);
  EXPECT_EQ(how_far_past_it_the_trap_returns, 0U);
}

INSTANTIATE_TEST_SUITE_P(
    EachUse, WhenFloatingPointIsOffAndSupervisorModeUsesIt,
    ::testing::Values(
        NamedInstruction{"a move into a register", riscv::FmvDX(0, riscv::kT1)},
        // From the result's own address, which supervisor mode has in t2.
        NamedInstruction{"a load", riscv::Fld(0, riscv::kT2, 0)},
        NamedInstruction{"a sum", riscv::FaddD(0, 0, 0)},
        NamedInstruction{"a store", riscv::Fsd(0, riscv::kT2, 0)},
        NamedInstruction{"a multiply and add in one",
                         riscv::FmaddD(0, 0, 0, 0)},
        NamedInstruction{"a compressed load", riscv::kCompressedFldThenNop},
        NamedInstruction{"a compressed store", riscv::kCompressedFsdThenNop},
        NamedInstruction{"a compressed load from the stack",
                         riscv::kCompressedFldspThenNop},
        NamedInstruction{"a compressed store to the stack",
                         riscv::kCompressedFsdspThenNop},
        NamedInstruction{"a read of its control register",
                         riscv::Csrr(riscv::kT0, riscv::kFcsr)},
        NamedInstruction{"a write of its control register",
                         riscv::Csrw(riscv::kFcsr, riscv::kZero)}),
    NamedByWhatItIs{});

// Something that changes the floating-point registers or their control
// register, as an instruction, and the state they were in before it.
struct ChangeOfFloatingPointState {
  const char* name;
  riscv::Word state_before;
  riscv::Word instruction;
};

void PrintTo(const ChangeOfFloatingPointState& change, std::ostream* out) {
  *out << change.name;
}

// A kernel that stops running a program looks at this state, and saves the
// registers only if it says dirty. A hart that did not mark it would have
// two programs share one set of registers.
class WhenSupervisorModeHasFloatingPointOnAndChangesItsState
    : public ::testing::TestWithParam<ChangeOfFloatingPointState> {};

TEST_P(WhenSupervisorModeHasFloatingPointOnAndChangesItsState,
       TheStateIsDirtyAndSaysSoInBothStatusRegisters) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInSupervisorModeAfter(
      CpuPlatformWithPages::kWithPagingOff, {},
      Then({
          riscv::SetFloatingPointState(riscv::kSstatus,
                                       GetParam().state_before),
          {GetParam().instruction},
          StoreSstatusThenCallMachineMode(),
      })));

  with_pages.RunUntilAsleep();

  // The instruction was executed: what entered machine mode was the call
  // after it.
  ASSERT_EQ(with_pages.Result(0), riscv::kEcallFromSupervisorMode + 1);
  const std::uint64_t mstatus = with_pages.Result(1);
  const std::uint64_t sstatus = with_pages.Result(2);
  EXPECT_EQ(riscv::FloatingPointStateIn(sstatus), riscv::kFloatingPointDirty);
  EXPECT_TRUE(riscv::SomeStateIsDirtyIn(sstatus));
  EXPECT_EQ(riscv::FloatingPointStateIn(mstatus), riscv::kFloatingPointDirty);
  EXPECT_TRUE(riscv::SomeStateIsDirtyIn(mstatus));
}

INSTANTIATE_TEST_SUITE_P(
    EachWay, WhenSupervisorModeHasFloatingPointOnAndChangesItsState,
    ::testing::Values(
        ChangeOfFloatingPointState{"a move into a register, from initial",
                                   riscv::kFloatingPointInitial,
                                   riscv::FmvDX(0, riscv::kT1)},
        ChangeOfFloatingPointState{"a move into a register, from clean",
                                   riscv::kFloatingPointClean,
                                   riscv::FmvDX(0, riscv::kT1)},
        ChangeOfFloatingPointState{
            "a write of its control register, from clean",
            riscv::kFloatingPointClean,
            riscv::Csrw(riscv::kFcsr, riscv::kZero)}),
    NamedByWhatItIs{});

// What a kernel does once it has saved a program's registers.
TEST(WhenSupervisorModeMarksDirtyFloatingPointStateClean,
     NeitherStatusRegisterSaysAnyStateIsDirty) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInSupervisorModeAfter(
      CpuPlatformWithPages::kWithPagingOff, {},
      Then({
          riscv::SetFloatingPointState(riscv::kSstatus,
                                       riscv::kFloatingPointDirty),
          riscv::MarkDirtyFloatingPointStateClean(riscv::kSstatus),
          StoreSstatusThenCallMachineMode(),
      })));

  with_pages.RunUntilAsleep();

  // Both registers were read with the state clean: neither word is one
  // that was never stored.
  const std::uint64_t mstatus = with_pages.Result(1);
  const std::uint64_t sstatus = with_pages.Result(2);
  ASSERT_EQ(riscv::FloatingPointStateIn(sstatus), riscv::kFloatingPointClean);
  ASSERT_EQ(riscv::FloatingPointStateIn(mstatus), riscv::kFloatingPointClean);
  EXPECT_FALSE(riscv::SomeStateIsDirtyIn(sstatus));
  EXPECT_FALSE(riscv::SomeStateIsDirtyIn(mstatus));
}

// A program's stack and a kernel's own memory are at addresses above
// 4 GiB, and a `float` on one is loaded and stored like anything else.
// The single is in the result's page, past the result itself.
constexpr std::uint64_t kPastTheResult = 0x100;
static_assert(CpuPlatformWithPages::kPages.result > 0xFFFF'FFFF);

TEST(WhenASingleIsLoadedThroughAnAddressAbove4GiB, TheLoadGetsWhatIsThere) {
  constexpr std::uint32_t kThere = 0x1234'5678;
  CpuPlatformWithPages with_pages;
  with_pages.Put(CpuPlatformWithPages::kResultPage + kPastTheResult, kThere);
  with_pages.Load(
      riscv::LoadASingle(CpuPlatformWithPages::kPages,
                         CpuPlatformWithPages::kPages.result + kPastTheResult));

  with_pages.RunUntilAsleep();

  const std::uint64_t loaded = with_pages.Result();
  EXPECT_EQ(loaded, kThere);
}

TEST(WhenASingleIsStoredThroughAnAddressAbove4GiB, TheStoreGoesThere) {
  constexpr std::uint32_t kToStore = 0x0BAD'CAFE;
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::StoreASingle(
      CpuPlatformWithPages::kPages,
      CpuPlatformWithPages::kPages.result + kPastTheResult, kToStore));

  with_pages.RunUntilAsleep();

  const std::uint64_t there_afterwards = with_pages.Result();
  EXPECT_EQ(there_afterwards, kToStore);
}

// Four bits of `mstatus` that are a monitor's way of keeping an operating
// system in hand: whose memory machine mode's own loads use, and whether
// the operating system may change its page tables, sleep, or return from
// a trap without the monitor hearing of it.
constexpr std::uint64_t kMachineModesOwnBits =
    (std::uint64_t{1} << riscv::kModifyPrivilege) |
    (std::uint64_t{1} << riscv::kTrapVirtualMemory) |
    (std::uint64_t{1} << riscv::kTimeoutWait) |
    (std::uint64_t{1} << riscv::kTrapSret);

TEST(WhenSupervisorModeSetsBitsOfMachineModesOwnInSstatus,
     NoneOfThemIsSetInMstatus) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInSupervisorModeAfter(
      CpuPlatformWithPages::kWithPagingOff, {},
      Then({
          riscv::SetBits(riscv::kSstatus, kMachineModesOwnBits, riscv::kT0),
          {riscv::kEcall},
      })));

  with_pages.RunUntilAsleep();

  // Machine mode was entered by the call, with the status it stored.
  ASSERT_EQ(with_pages.Result(0), riscv::kEcallFromSupervisorMode + 1);
  const std::uint64_t mstatus = with_pages.Result(1);
  EXPECT_EQ(mstatus & kMachineModesOwnBits, 0U);
}

TEST(WhenMachineModeHasSetBitsOfItsOwnInMstatus,
     SupervisorModeDoesNotReadThemInSstatus) {
  // All but the one that a return to supervisor mode clears.
  constexpr std::uint64_t kThreeOfThem =
      kMachineModesOwnBits & ~(std::uint64_t{1} << riscv::kModifyPrivilege);
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInSupervisorModeAfter(
      CpuPlatformWithPages::kWithPagingOff,
      riscv::SetBits(riscv::kMstatus, kThreeOfThem, riscv::kT1),
      StoreSstatusThenCallMachineMode()));

  with_pages.RunUntilAsleep();

  // Supervisor mode did read `sstatus`, and went on to call machine mode,
  // which read the three back: they were set.
  ASSERT_EQ(with_pages.Result(0), riscv::kEcallFromSupervisorMode + 1);
  const std::uint64_t mstatus = with_pages.Result(1);
  ASSERT_EQ(mstatus & kThreeOfThem, kThreeOfThem);
  const std::uint64_t sstatus = with_pages.Result(2);
  EXPECT_EQ(sstatus & kMachineModesOwnBits, 0U);
}

// A use of the atomic instructions on a cell of memory, whose address the
// instructions find in t1, with where their result goes in t2: what is in
// the cell before, and what is to be found afterwards, as the result and
// in the cell.
struct UseOfAtomics {
  const char* name;
  std::uint64_t cell_before;
  riscv::Program instructions;
  std::uint64_t result;
  std::uint64_t cell_after;
};

// And whether the hart reaches the cell by direct memory access or by a
// transaction each time.
struct UseOfAtomicsEitherWay {
  UseOfAtomics use;
  bool over_the_bus;
};

void PrintTo(const UseOfAtomicsEitherWay& way, std::ostream* out) {
  *out << way.use.name
       << (way.over_the_bus ? ", over the bus" : ", by direct access");
}

std::vector<UseOfAtomicsEitherWay> EitherWay(
    const std::vector<UseOfAtomics>& uses) {
  std::vector<UseOfAtomicsEitherWay> either_way;
  for (const bool over_the_bus : {false, true}) {
    for (const UseOfAtomics& use : uses) {
      either_way.push_back({.use = use, .over_the_bus = over_the_bus});
    }
  }
  return either_way;
}

// What a use of the atomics left: its result, and what is in the cell.
struct LeftByAtomics {
  std::uint64_t result;
  std::uint64_t cell;
};

// Runs a use of the atomics on a platform of its own.
LeftByAtomics WhatIsLeftBy(const UseOfAtomicsEitherWay& way) {
  constexpr std::uint64_t kCell = CpuPlatformWithPages::kFirstSparePage;
  CpuPlatformWithPages with_pages;
  if (way.over_the_bus) with_pages.WithdrawDirectAccess();
  with_pages.Put(kCell, way.use.cell_before);
  // The RAM starts as zeros, which a program that stored nothing would
  // leave looking like a result of zero.
  with_pages.Put(CpuPlatformWithPages::kResultPage, ~std::uint64_t{0});
  with_pages.Load(riscv::RunWithACell(kCell, CpuPlatformWithPages::kResultPage,
                                      way.use.instructions));

  with_pages.RunUntilAsleep();

  if (way.over_the_bus) {
    // It was: an instruction fetched is a transaction, and with direct
    // access the whole program is a handful.
    EXPECT_GE(with_pages.Transactions(), way.use.instructions.size());
  }
  return {.result = with_pages.Result(), .cell = with_pages.At(kCell)};
}

// What a store-conditional answers with when it stored, and when not.
constexpr std::uint64_t kStored = 0;
constexpr std::uint64_t kDidNotStore = 1;
// What the cell holds before anything, and what a store-conditional is
// given to store there.
constexpr std::uint64_t kInTheCell = 0x11;
constexpr std::int32_t kGiven = 0x5A;

// The instructions that the uses of a store-conditional are put together
// from. t3 = what it is given, and t5 = the address of the cell after the
// one in t1. Each use ends by storing the last answer as the result.
constexpr riscv::Word kT3IsGiven = riscv::Li(riscv::kT3, kGiven);
constexpr riscv::Word kT5IsTheNextCell = riscv::Addi(riscv::kT5, riscv::kT1, 8);
constexpr riscv::Word kReserveTheCell = riscv::LrD(riscv::kT0, riscv::kT1);
constexpr riscv::Word kReserveTheNextCell = riscv::LrD(riscv::kT0, riscv::kT5);
constexpr riscv::Word kStoreConditionalToTheCell =
    riscv::ScD(riscv::kT4, riscv::kT1, riscv::kT3);
constexpr riscv::Word kStoreConditionalToTheNextCell =
    riscv::ScD(riscv::kT4, riscv::kT5, riscv::kT3);
constexpr riscv::Word kTheAnswerIsTheResult =
    riscv::Sd(riscv::kT4, riscv::kT2, 0);

// 🎓 A kernel's locks and counters are made of these. A load-reserved and
// a store-conditional make a read and a later write one act: the store is
// made only if the hart still holds the reservation the load took.
class WhenAStoreConditionalFollowsALoadReservedOfItsCell
    : public ::testing::TestWithParam<UseOfAtomicsEitherWay> {};

TEST_P(WhenAStoreConditionalFollowsALoadReservedOfItsCell,
       ItStoresAndAnswersZero) {
  const LeftByAtomics left = WhatIsLeftBy(GetParam());

  EXPECT_EQ(left.result, kStored);
  EXPECT_EQ(left.cell, GetParam().use.cell_after);
}

INSTANTIATE_TEST_SUITE_P(
    EitherWay, WhenAStoreConditionalFollowsALoadReservedOfItsCell,
    ::testing::ValuesIn(EitherWay({{"at once",
                                    kInTheCell,
                                    {kT3IsGiven, kReserveTheCell,
                                     kStoreConditionalToTheCell,
                                     kTheAnswerIsTheResult},
                                    kStored,
                                    kGiven}})),
    NamedByWhatItIs{});

// A hart has one reservation, on one address, and any store-conditional
// gives it up, whether or not it stored. That second half is how a kernel
// makes sure that a program it interrupted between the two halves of the
// pair cannot finish the pair as if nothing had happened: on its way out
// of every trap Linux executes a store-conditional to its own stack.
class WhenAStoreConditionalFindsNoReservationOnItsCell
    : public ::testing::TestWithParam<UseOfAtomicsEitherWay> {};

TEST_P(WhenAStoreConditionalFindsNoReservationOnItsCell,
       ItAnswersOneAndStoresNothing) {
  const LeftByAtomics left = WhatIsLeftBy(GetParam());

  EXPECT_EQ(left.result, kDidNotStore);
  EXPECT_EQ(left.cell, GetParam().use.cell_after);
}

INSTANTIATE_TEST_SUITE_P(
    EachReason, WhenAStoreConditionalFindsNoReservationOnItsCell,
    ::testing::ValuesIn(EitherWay({
        {"with no load-reserved before it",
         kInTheCell,
         {kT3IsGiven, kStoreConditionalToTheCell, kTheAnswerIsTheResult},
         kDidNotStore,
         kInTheCell},
        // The first stored what it was given, and the second is given
        // something else.
        {"after a store-conditional that stored",
         kInTheCell,
         {kT3IsGiven, kReserveTheCell, kStoreConditionalToTheCell,
          riscv::Li(riscv::kT3, 0x7B), kStoreConditionalToTheCell,
          kTheAnswerIsTheResult},
         kDidNotStore,
         kGiven},
        {"with another cell reserved",
         kInTheCell,
         {kT3IsGiven, kT5IsTheNextCell, kReserveTheNextCell,
          kStoreConditionalToTheCell, kTheAnswerIsTheResult},
         kDidNotStore,
         kInTheCell},
        {"after a store-conditional to another cell",
         kInTheCell,
         {kT3IsGiven, kT5IsTheNextCell, kReserveTheCell,
          kStoreConditionalToTheNextCell, kStoreConditionalToTheCell,
          kTheAnswerIsTheResult},
         kDidNotStore,
         kInTheCell},
        {"which was reserved before another cell was",
         kInTheCell,
         {kT3IsGiven, kT5IsTheNextCell, kReserveTheCell, kReserveTheNextCell,
          kStoreConditionalToTheCell, kTheAnswerIsTheResult},
         kDidNotStore,
         kInTheCell},
    })),
    NamedByWhatItIs{});

// The ones that do it in one instruction: what was in the cell comes back
// in a register, and what the operation makes of it and of the register
// it was given is left in the cell.
class WhenAProgramUsesAnAtomicMemoryOperation
    : public ::testing::TestWithParam<UseOfAtomicsEitherWay> {};

TEST_P(WhenAProgramUsesAnAtomicMemoryOperation,
       ItGivesBackWhatWasThereAndLeavesWhatTheOperationMakes) {
  const LeftByAtomics left = WhatIsLeftBy(GetParam());

  EXPECT_EQ(left.result, GetParam().use.result);
  EXPECT_EQ(left.cell, GetParam().use.cell_after);
}

// An operation on t1's cell and t3 whose answer, in t0, is the result.
riscv::Program WithT3(std::int32_t given, riscv::Word operation) {
  return {
      riscv::Li(riscv::kT3, given),
      operation,
      riscv::Sd(riscv::kT0, riscv::kT2, 0),
  };
}

INSTANTIATE_TEST_SUITE_P(
    EachOperation, WhenAProgramUsesAnAtomicMemoryOperation,
    ::testing::ValuesIn(EitherWay({
        {"a swap", 0x11,
         WithT3(0x22, riscv::AmoswapD(riscv::kT0, riscv::kT1, riscv::kT3)),
         0x11, 0x22},
        {"a sum", 0x11,
         WithT3(0x22, riscv::AmoaddD(riscv::kT0, riscv::kT1, riscv::kT3)), 0x11,
         0x33},
        // The low half of the cell alone: what comes back has its sign
        // carried up, and the upper half of the cell is left as it was.
        {"an or, of 32 bits", 0xAAAA'AAAA'8000'0011,
         WithT3(0x30, riscv::AmoorW(riscv::kT0, riscv::kT1, riscv::kT3)),
         0xFFFF'FFFF'8000'0011, 0xAAAA'AAAA'8000'0031},
        {"the greater, with a greater", 0x11,
         WithT3(0x22, riscv::AmomaxD(riscv::kT0, riscv::kT1, riscv::kT3)), 0x11,
         0x22},
        // All ones is below zero as a signed number, and above everything
        // as an unsigned one.
        {"the greater, with a number below zero", 0x11,
         WithT3(-1, riscv::AmomaxD(riscv::kT0, riscv::kT1, riscv::kT3)), 0x11,
         0x11},
    })),
    NamedByWhatItIs{});

// A use of a word at an address that is not a multiple of four, by the
// instruction that makes it, with the address in t1, and the trap it is.
struct MisalignedUse {
  const char* name;
  riscv::Word instruction;
  riscv::Word cause;
};

void PrintTo(const MisalignedUse& use, std::ostream* out) { *out << use.name; }

// An atomic is a load and a store in one, and is refused as a store: a
// handler that makes misaligned loads on a program's behalf must not
// take one for a load, since it could only make half of it.
constexpr std::array<MisalignedUse, 3> kEachMisalignedUse{
    {
        {
            .name = "a load",
            .instruction = riscv::Lw(riscv::kT0, riscv::kT1, 0),
            .cause = riscv::kMisalignedLoad,
        },
        {
            .name = "a store",
            .instruction = riscv::Sw(riscv::kT0, riscv::kT1, 0),
            .cause = riscv::kMisalignedStore,
        },
        {
            .name = "an atomic sum",
            .instruction = riscv::AmoaddW(riscv::kT0, riscv::kT1, riscv::kT3),
            .cause = riscv::kMisalignedStore,
        },
    },
};

// An address in the RAM that is one past a multiple of four.
constexpr std::uint64_t kOddAddress =
    CpuPlatformWithPages::kFirstSparePage + 0x101;

// 🎓 A hart may refuse a load or a store at an address that is not a
// multiple of its size, and this one does. A kernel is written as if no
// hart did, so something under it catches the trap and makes the access
// itself, a byte at a time. For that the trap has to say which instruction
// and which address.
class WhenSupervisorModeUsesAWordAtAnOddAddress
    : public ::testing::TestWithParam<MisalignedUse> {};

TEST_P(WhenSupervisorModeUsesAWordAtAnOddAddress,
       MachineModeTakesTheTrapOfThatUseWhichSaysTheInstructionAndTheAddress) {
  // The address is made from the result's own, which supervisor mode has
  // in t2, by one instruction, so the use is the one after it.
  constexpr std::int32_t kOddOffsetFromTheResult = 0x101;
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::RunInSupervisorModeAfter(
      CpuPlatformWithPages::kWithPagingOff, {},
      {
          riscv::Addi(riscv::kT1, riscv::kT2, kOddOffsetFromTheResult),
          GetParam().instruction,
      }));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why = with_pages.Result(0);
  const std::uint64_t how_far_into_its_code = with_pages.Result(3);
  const std::uint64_t where = with_pages.Result(4);
  EXPECT_EQ(why, GetParam().cause + 1);
  EXPECT_EQ(how_far_into_its_code, 4U);
  EXPECT_EQ(where, CpuPlatformWithPages::kResultPage + kOddOffsetFromTheResult);
}

INSTANTIATE_TEST_SUITE_P(EachUse, WhenSupervisorModeUsesAWordAtAnOddAddress,
                         ::testing::ValuesIn(kEachMisalignedUse),
                         NamedByWhatItIs{});

// A monitor may hand the two traps down, to a kernel that would sooner see
// to them itself.
class WhenSupervisorModeUsesAWordAtAnOddAddressAndTheTrapIsHandedDown
    : public ::testing::TestWithParam<MisalignedUse> {};

TEST_P(WhenSupervisorModeUsesAWordAtAnOddAddressAndTheTrapIsHandedDown,
       SupervisorModeTakesItWithTheAddressAndTheProgramRunsOnPastIt) {
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::TakeAMisalignedAccessInSupervisorMode(
      CpuPlatformWithPages::kWithPagingOff, kOddAddress,
      GetParam().instruction));

  with_pages.RunUntilAsleep();

  // The program stores the cause with one added, and zero for no trap.
  const std::uint64_t why = with_pages.Result(0);
  const std::uint64_t where = with_pages.Result(1);
  const std::uint64_t the_program_ran_on = with_pages.Result(2);
  EXPECT_EQ(why, GetParam().cause + 1);
  EXPECT_EQ(where, kOddAddress);
  EXPECT_EQ(the_program_ran_on, 1U);
}

INSTANTIATE_TEST_SUITE_P(
    EachUse, WhenSupervisorModeUsesAWordAtAnOddAddressAndTheTrapIsHandedDown,
    ::testing::ValuesIn(kEachMisalignedUse), NamedByWhatItIs{});

// What the handler of such a trap does. Here it is in supervisor mode, as
// Linux's own is from 6.16, which asks OpenSBI to hand the two traps down.
// For a kernel that does not ask, OpenSBI does the same one mode up, from
// `mepc` and `mtval`. The trap says where, the instruction it names says
// what (this handler is told: a word, from t0), and the handler stores the
// word a byte at a time and returns past the instruction.
TEST(WhenAHandlerMakesTheStoreThatAHartRefusedAtAnOddAddress,
     TheWordIsThereAndTheProgramRunsOn) {
  constexpr std::uint32_t kWord = 0x1234'5678;
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::TakeAMisalignedAccessInSupervisorMode(
      CpuPlatformWithPages::kWithPagingOff, kOddAddress,
      riscv::Sw(riscv::kT0, riscv::kT1, 0),
      /*then_the_handler=*/riscv::StoreTheWordInT0AByteAtATimeAtT5(),
      /*t0=*/kWord));

  with_pages.RunUntilAsleep();

  // The handler ran: the word there is its doing, and not the
  // instruction's.
  ASSERT_EQ(with_pages.Result(0), riscv::kMisalignedStore + 1);
  const auto there = static_cast<std::uint32_t>(with_pages.At(kOddAddress));
  const std::uint64_t the_program_ran_on = with_pages.Result(2);
  EXPECT_EQ(there, kWord);
  EXPECT_EQ(the_program_ran_on, 1U);
}

// 🎓 Machine mode's addresses are not translated. A monitor that has to
// look at a kernel's memory, at the instruction it trapped on or at a
// buffer it was handed, sets MPRV, and its loads and stores are then made
// as the mode it was entered from would make them: through the kernel's
// page tables. OpenSBI does it for every misaligned access it makes on a
// kernel's behalf.
TEST(WhenMachineModeSetsMprvAfterATrapFromSupervisorModeUnderPaging,
     ItsLoadsAndStoresGoThroughTheSupervisorsPageTables) {
  constexpr std::uint64_t kThere = 0x0123'4567'89AB'CDEF;
  CpuPlatformWithPages with_pages;
  with_pages.Map(CpuPlatformWithPages::kSpareAddresses,
                 CpuPlatformWithPages::kFirstSparePage,
                 CpuPlatformWithPages::kData);
  with_pages.Put(CpuPlatformWithPages::kFirstSparePage + 0x18, kThere);
  with_pages.Load(riscv::LoadAsSupervisorModeWouldFromMachineMode(
      CpuPlatformWithPages::kPages, CpuPlatformWithPages::kProgramPage,
      CpuPlatformWithPages::kInASparePage));

  with_pages.RunUntilAsleep();

  // Loaded from an address only the tables lead to, and stored to another.
  EXPECT_EQ(with_pages.Result(), kThere);
}

TEST(WhenNothingHasWrittenSatp, ItReadsAsPagingOff) {
  CpuPlatformWithPages with_pages;
  // The RAM starts as zeros, which a program that stored nothing would
  // leave looking like the answer.
  with_pages.Put(CpuPlatformWithPages::kResultPage, ~std::uint64_t{0});
  with_pages.Load(riscv::StoreWhatSatpReadsAsBeforeAndAfterWriting(
      {}, CpuPlatformWithPages::kResultPage));

  with_pages.RunUntilAsleep();

  const std::uint64_t at_first = with_pages.Result(0);
  EXPECT_EQ(at_first, 0U);
}

// 🎓 An address-space identifier is a number a kernel gives each program,
// in sixteen bits of `satp`, so that a hart can keep one program's
// translations while it runs another. A hart may have fewer bits of it
// than sixteen, or none, and a kernel finds out how many by writing ones
// and reading them back. This hart keeps translations by address alone,
// so it has to say none.
TEST(WhenSatpIsWrittenWithAnAddressSpaceIdentifier,
     TheIdentifierReadsBackAsZeroAndTheRestAsWritten) {
  constexpr std::uint64_t kPagingOn =
      riscv::SatpForSv39(CpuPlatformWithPages::kFirstTable);
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::StoreWhatSatpReadsAsBeforeAndAfterWriting(
      {kPagingOn | riscv::kSatpIdentifier}, CpuPlatformWithPages::kResultPage));

  with_pages.RunUntilAsleep();

  const std::uint64_t once_written = with_pages.Result(1);
  EXPECT_EQ(once_written, kPagingOn);
}

// A kind of paging, by the number that asks for it in `satp`.
struct KindOfPaging {
  const char* name;
  std::uint64_t number;
};

void PrintTo(const KindOfPaging& kind, std::ostream* out) { *out << kind.name; }

// A kernel asks for the biggest kind of paging it knows and looks at what
// the hart kept, and Linux knows Sv57. This hart has Sv39 and no other,
// as most chips have, so that Sv39 is what a kernel ends up with.
class WhenSatpIsWrittenWithAKindOfPagingTheHartHasNot
    : public ::testing::TestWithParam<KindOfPaging> {};

TEST_P(WhenSatpIsWrittenWithAKindOfPagingTheHartHasNot, ItKeepsWhatItHad) {
  constexpr std::uint64_t kPagingOn =
      riscv::SatpForSv39(CpuPlatformWithPages::kFirstTable);
  // With another table than the first write's, so that a hart which kept
  // its kind of paging and took the rest would not pass.
  const std::uint64_t another_kind_and_table =
      riscv::Satp(GetParam().number, CpuPlatformWithPages::kSecondTable);
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::StoreWhatSatpReadsAsBeforeAndAfterWriting(
      {kPagingOn, another_kind_and_table}, CpuPlatformWithPages::kResultPage));

  with_pages.RunUntilAsleep();

  const std::uint64_t after_the_second_write = with_pages.Result(2);
  EXPECT_EQ(after_the_second_write, kPagingOn);
}

INSTANTIATE_TEST_SUITE_P(
    EachKind, WhenSatpIsWrittenWithAKindOfPagingTheHartHasNot,
    ::testing::Values(KindOfPaging{"Sv48", 9}, KindOfPaging{"Sv57", 10},
                      KindOfPaging{"one the standard keeps back", 11},
                      KindOfPaging{"one the standard has not got", 15}),
    NamedByWhatItIs{});

// Direct access is to the RAM, by the addresses the RAM has, and a
// translation ends in one of those. So paging costs a program none of it.
TEST(WhenAProgramUnderPagingLoopsInAMemoryThatOffersDirectAccess,
     TheCpuStillDoesNotUseTheBusForIt) {
  // As many as the millisecond that RunUntilAsleep runs for has room for.
  constexpr std::uint64_t kIterations = 2048;
  CpuPlatformWithPages with_pages;
  with_pages.Load(riscv::CountDownUnderPagingStoringEachCount(
      CpuPlatformWithPages::kPages, kIterations));

  // Three instructions each time round, at 100 ns an instruction: 0.6 ms.
  with_pages.RunUntilAsleep();

  // The loop finished: the last count it stored is one.
  ASSERT_EQ(with_pages.Result(), 1U);
  // Without direct access every fetch and every store is a transaction,
  // four each time round.
  EXPECT_LT(with_pages.Transactions(), kIterations);
}

// Two pages that follow each other in a program's addresses can be
// anywhere in the RAM, and an instruction of four bytes can begin two
// bytes before the end of the first.
static_assert(CpuPlatformWithPages::kSecondSparePage !=
              CpuPlatformWithPages::kFirstSparePage + 0x1000);

TEST(WhenAnInstructionLiesAcrossTwoPagesThatAreNotNeighboursInTheRam,
     ItIsReadAHalfFromEach) {
  constexpr std::uint64_t kFirstPage = CpuPlatformWithPages::kSpareAddresses;
  constexpr std::uint64_t kSecondPage = kFirstPage + 0x1000;
  constexpr std::uint64_t kTwoBytesBeforeTheEnd = 0xFFE;
  CpuPlatformWithPages with_pages;
  with_pages.Map(kFirstPage, CpuPlatformWithPages::kFirstSparePage,
                 CpuPlatformWithPages::kCode);
  with_pages.Map(kSecondPage, CpuPlatformWithPages::kSecondSparePage,
                 CpuPlatformWithPages::kCode);
  // t0 = 0x123, a half of it in each page, and then a return.
  const riscv::Word across = riscv::Addi(riscv::kT0, riscv::kZero, 0x123);
  const auto first_half = static_cast<std::uint16_t>(across);
  const auto second_half = static_cast<std::uint16_t>(across >> 16U);
  with_pages.Put(CpuPlatformWithPages::kFirstSparePage + kTwoBytesBeforeTheEnd,
                 first_half);
  with_pages.Put(CpuPlatformWithPages::kSecondSparePage, second_half);
  with_pages.Put(CpuPlatformWithPages::kSecondSparePage + 2,
                 riscv::Jalr(riscv::kZero, riscv::kRa, 0));
  with_pages.Load(riscv::StoreWhatTheCodeAtAnAddressLeavesInT0(
      CpuPlatformWithPages::kPages, kFirstPage + kTwoBytesBeforeTheEnd));

  with_pages.RunUntilAsleep();

  EXPECT_EQ(with_pages.Result(), 0x123U);
}

// A hart reads no more of an instruction than the instruction has. The
// last two bytes of a program's last page can be a whole one.
TEST(WhenATwoByteInstructionEndsAPageAndThePageAfterIsNotMapped,
     ItRunsAllTheSame) {
  constexpr std::uint64_t kLastPage = CpuPlatformWithPages::kSpareAddresses;
  CpuPlatformWithPages with_pages;
  with_pages.Map(kLastPage, CpuPlatformWithPages::kFirstSparePage,
                 CpuPlatformWithPages::kCode);
  // t0 = 0x5A, and then a return in the page's last two bytes.
  with_pages.Put(CpuPlatformWithPages::kFirstSparePage + 0xFFA,
                 riscv::Addi(riscv::kT0, riscv::kZero, 0x5A));
  with_pages.Put(CpuPlatformWithPages::kFirstSparePage + 0xFFE,
                 riscv::kCompressedRet);
  with_pages.Load(riscv::StoreWhatTheCodeAtAnAddressLeavesInT0(
      CpuPlatformWithPages::kPages, kLastPage + 0xFFA));

  with_pages.RunUntilAsleep();

  EXPECT_EQ(with_pages.Result(), 0x5AU);
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
  AddTheCpu(platform, "cpu", {{"xlen", 64}, {"reset_vector", kRamBase}});
  platform.Add("bus", "router",
               {
                   {"outputs", 3},
                   {"out0.base", kRamBase},
                   {"out0.size", 0x1000},
                   {"out1.base", kPlicBase},
                   {"out1.size", 0x400'0000},
                   {"out2.base", kDeviceBase},
                   {"out2.size", 0x100},
               });
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
