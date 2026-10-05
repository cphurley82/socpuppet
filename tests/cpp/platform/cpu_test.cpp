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

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/support/counting_probe.h"
#include "tests/cpp/support/interrupt_source.h"
#include "tests/cpp/support/recording_target.h"
#include "tests/cpp/support/riscv_program.h"

using ::testing::AllOf;
using ::testing::HasSubstr;
using ::testing::ThrowsMessage;

namespace {

// A platform with a CPU and nothing else but a RAM for its program.
struct CpuPlatform {
  // Not zero, so that a CPU that ignored its reset vector would not pass.
  static constexpr std::uint64_t kResetVector = 0x100;

  explicit CpuPlatform(std::uint64_t xlen) {
    platform.Add("cpu", "dbt_rise_cpu",
                 {{"xlen", xlen}, {"reset_vector", kResetVector}});
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
        "counting_probe", [](const char* name, const socpuppet::Config&) {
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
// interrupts it on the line `cpu_input` ("irq" or "timer_irq").
struct CpuPlatformWithAnInterruptSource {
  static constexpr std::uint64_t kRamBase = 0x8000'0000;
  static constexpr std::uint64_t kDeviceBase = 0x1000'0000;

  CpuPlatformWithAnInterruptSource(
      const std::string& cpu_input,
      const std::function<void(InterruptSource&)>& interrupts)
      : platform{WithAnInterruptSource(interrupts)} {
    platform.Add("cpu", "dbt_rise_cpu",
                 {{"xlen", 64}, {"reset_vector", kRamBase}});
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

  static socpuppet::Registry WithAnInterruptSource(
      const std::function<void(InterruptSource&)>& interrupts) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    registry.Add("interrupt_source", [interrupts](const char* name,
                                                  const socpuppet::Config&) {
      auto module = std::make_unique<InterruptSource>(name, interrupts);
      std::vector<socpuppet::Port> ports{
          socpuppet::TargetPort("socket", module->socket),
          socpuppet::WireSourcePort("line", module->line)};
      return socpuppet::Instance{.module = std::move(module),
                                 .ports = std::move(ports)};
    });
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
  registry.Add("probe", [&](const char* name, const socpuppet::Config&) {
    auto module =
        std::make_unique<RecordingTarget>(name, probed, sc_core::SC_ZERO_TIME);
    std::vector<socpuppet::Port> ports{
        socpuppet::TargetPort("socket", module->socket)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
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
