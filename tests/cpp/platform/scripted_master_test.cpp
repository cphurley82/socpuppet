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

#include "socpuppet/core/script.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/platform.h"
#include "tests/cpp/support/interrupt_source.h"
#include "tests/cpp/support/line_driver.h"
#include "tests/cpp/support/recording_target.h"

namespace socpuppet {

using ::testing::AllOf;
using ::testing::HasSubstr;
using ::testing::ThrowsMessage;

namespace {

sc_core::sc_time Nanoseconds(double count) { return {count, sc_core::SC_NS}; }

// What drives a master's input lines in a test. A line with no driver is
// left unconnected.
struct Lines {
  Drive irq = nullptr;
  Drive reset = nullptr;
};

// A scripted bus master wired straight to a 0x100-byte RAM.
struct MasterWithRam {
  explicit MasterWithRam(std::function<Script()> script,
                         const Lines& lines = {})
      : platform{WithLineDrivers(lines.irq, lines.reset)} {
    const Drive& irq = lines.irq;
    const Drive& reset = lines.reset;
    platform.Add("cpu", "scripted_bus_master");
    platform.Add("ram", "memory", {{"size", 0x100}});
    platform.Bind("cpu.socket", "ram.socket");
    if (irq) {
      platform.Add("irq_driver", "irq_driver");
      platform.Bind("irq_driver.line", "cpu.irq");
    }
    if (reset) {
      platform.Add("reset_driver", "reset_driver");
      platform.Bind("reset_driver.line", "cpu.reset");
    }
    platform.ModuleAt<ScriptedBusMaster>("cpu").SetScript(std::move(script));
    platform.Elaborate();
  }

  std::uint32_t Peek32(std::uint64_t address) {
    std::uint32_t value = 0;
    platform.DebugRead("cpu.socket", address,
                       std::as_writable_bytes(std::span{&value, 1}));
    return value;
  }

  static Registry WithLineDrivers(const Drive& irq, const Drive& reset) {
    Registry registry = BuiltinComponents();
    for (const auto& [implementation, body] :
         {std::pair{"irq_driver", irq}, std::pair{"reset_driver", reset}}) {
      registry.Add(implementation, [body](const char* name, const Config&) {
        auto module = std::make_unique<LineDriver>(name, body);
        std::vector<Port> ports{WireSourcePort("line", module->line)};
        return Instance{.module = std::move(module), .ports = std::move(ports)};
      });
    }
    return registry;
  }

  Platform platform;
};

// A scripted bus master wired straight to a device that interrupts it. Any
// write the script makes quiets the device.
struct MasterWithAnInterruptSource {
  MasterWithAnInterruptSource(
      std::function<Script()> script,
      const std::function<void(InterruptSource&)>& interrupts)
      : platform{WithAnInterruptSource(interrupts)} {
    platform.Add("cpu", "scripted_bus_master");
    platform.Add("device", "interrupt_source");
    platform.Bind("cpu.socket", "device.socket");
    platform.Bind("device.line", "cpu.irq");
    platform.ModuleAt<ScriptedBusMaster>("cpu").SetScript(std::move(script));
    platform.Elaborate();
  }

  int TimesQuieted() {
    return platform.ModuleAt<InterruptSource>("device").TimesQuieted();
  }

  static Registry WithAnInterruptSource(
      const std::function<void(InterruptSource&)>& interrupts) {
    Registry registry = BuiltinComponents();
    registry.Add("interrupt_source", [interrupts](const char* name,
                                                  const Config&) {
      auto module = std::make_unique<InterruptSource>(name, interrupts);
      std::vector<Port> ports{TargetPort("socket", module->socket),
                              WireSourcePort("line", module->line)};
      return Instance{.module = std::move(module), .ports = std::move(ports)};
    });
    return registry;
  }

  Platform platform;
};

// A scripted bus master wired straight to a target that writes down every
// access it gets.
struct MasterWithAProbe {
  explicit MasterWithAProbe(std::function<Script()> script)
      : platform{WithAProbe(accesses)} {
    platform.Add("cpu", "scripted_bus_master");
    platform.Add("probe", "probe");
    platform.Bind("cpu.socket", "probe.socket");
    platform.ModuleAt<ScriptedBusMaster>("cpu").SetScript(std::move(script));
    platform.Elaborate();
  }

  static Registry WithAProbe(std::vector<RecordedAccess>& accesses) {
    Registry registry = BuiltinComponents();
    registry.Add("probe", [&accesses](const char* name, const Config&) {
      auto module = std::make_unique<RecordingTarget>(name, accesses,
                                                      sc_core::SC_ZERO_TIME);
      std::vector<Port> ports{TargetPort("socket", module->socket)};
      return Instance{.module = std::move(module), .ports = std::move(ports)};
    });
    return registry;
  }

  // Declared before the platform, which holds a reference to it.
  std::vector<RecordedAccess> accesses;
  Platform platform;
};

}  // namespace

TEST(WhenAScriptReadsBackSixBytesItWrote, ItGetsTheSameBytes) {
  std::vector<std::uint8_t> read_back;
  MasterWithRam fixture{[&]() -> Script {
    co_await Write(0x10, {0x11, 0x22, 0x33, 0x44, 0x55, 0x66});
    read_back = co_await Read(0x10, 6);
  }};

  fixture.platform.Run();

  EXPECT_EQ(read_back,
            (std::vector<std::uint8_t>{0x11, 0x22, 0x33, 0x44, 0x55, 0x66}));
}

TEST(WhenAScriptWritesSixBytes, TheTargetSeesOneAccess) {
  MasterWithAProbe fixture{[]() -> Script {
    co_await Write(0x10, {0x11, 0x22, 0x33, 0x44, 0x55, 0x66});
  }};

  fixture.platform.Run();

  EXPECT_EQ(fixture.accesses.size(), 1U);
}

TEST(WhenAScriptReadsAnAddressItWroteEarlier, TheReadReturnsTheWrittenValue) {
  MasterWithRam fixture{[]() -> Script {
    co_await Write32(0x10, 0xC0FFEE);
    const std::uint32_t read_back = co_await Read32(0x10);
    co_await Write32(0x20, read_back);
  }};

  fixture.platform.Run();

  EXPECT_EQ(fixture.Peek32(0x20), 0xC0FFEEU);
}

TEST(WhenAScriptWaits, ItsNextOpHappensThatMuchLater) {
  MasterWithRam fixture{[]() -> Script {
    co_await Wait(Picoseconds{10'000});
    co_await Write32(0x10, 0xC0FFEE);
  }};

  fixture.platform.Run(Nanoseconds(9));
  const std::uint32_t before = fixture.Peek32(0x10);
  fixture.platform.Run(Nanoseconds(2));
  const std::uint32_t after = fixture.Peek32(0x10);

  EXPECT_EQ(before, 0U);
  EXPECT_EQ(after, 0xC0FFEEU);
}

TEST(WhenAnExpectedValueIsNotTheOneInMemory,
     TheRunFailsNamingAddressExpectedAndActual) {
  MasterWithRam fixture{[]() -> Script {
    co_await Write32(0x10, 0xBAD);
    co_await Expect32(0x10, 0xC0FFEE);
  }};

  EXPECT_THAT(
      [&] { fixture.platform.Run(); },
      ThrowsMessage<ExpectationFailed>(
          AllOf(HasSubstr("0x10"), HasSubstr("0xc0ffee"), HasSubstr("0xbad"))));
}

TEST(WhenAnExpectedValueIsNotTheOneInMemory, TheScriptDoesNotCarryOn) {
  MasterWithRam fixture{[]() -> Script {
    co_await Expect32(0x10, 0xC0FFEE);
    co_await Write32(0x20, 1);
  }};

  EXPECT_THROW(fixture.platform.Run(), ExpectationFailed);

  EXPECT_EQ(fixture.Peek32(0x20), 0U);
}

TEST(WhenAScriptWaitsForTheInterrupt, ItCarriesOnOnceTheLineRises) {
  MasterWithRam fixture{[]() -> Script {
                          co_await WaitIrq();
                          co_await Write32(0x10, 0xC0FFEE);
                        },
                        {.irq = [](LineDriver& irq) {
                          irq.WaitFor(Nanoseconds(10));
                          irq.Set(true);
                        }}};

  fixture.platform.Run(Nanoseconds(9));
  const std::uint32_t before = fixture.Peek32(0x10);
  fixture.platform.Run(Nanoseconds(2));
  const std::uint32_t after = fixture.Peek32(0x10);

  EXPECT_EQ(before, 0U);
  EXPECT_EQ(after, 0xC0FFEEU);
}

TEST(WhenAScriptQuietsTheDeviceThatInterruptedAndWaitsAgain,
     ItCarriesOnOncePerInterrupt) {
  // The script is ready to quiet the device three times, and the device
  // interrupts twice.
  MasterWithAnInterruptSource fixture{[]() -> Script {
                                        for (int times = 0; times < 3;
                                             ++times) {
                                          co_await WaitIrq();
                                          co_await Write32(0, 0);
                                        }
                                      },
                                      [](InterruptSource& device) {
                                        device.Raise();
                                        // Later, so that the script has quieted
                                        // the first interrupt.
                                        device.WaitFor(Nanoseconds(10));
                                        device.Raise();
                                      }};

  fixture.platform.Run();

  EXPECT_EQ(fixture.TimesQuieted(), 2);
}

TEST(WhenResetIsHeldFromTimeZero, TheScriptStartsOnlyOnceItIsReleased) {
  MasterWithRam fixture{[]() -> Script { co_await Write32(0x10, 0xC0FFEE); },
                        {.reset = [](LineDriver& reset) {
                          reset.Set(true);
                          reset.WaitFor(Nanoseconds(10));
                          reset.Set(false);
                        }}};

  fixture.platform.Run(Nanoseconds(9));
  const std::uint32_t during_reset = fixture.Peek32(0x10);
  fixture.platform.Run(Nanoseconds(2));
  const std::uint32_t after_release = fixture.Peek32(0x10);

  EXPECT_EQ(during_reset, 0U);
  EXPECT_EQ(after_release, 0xC0FFEEU);
}

TEST(WhenResetIsPulsedPartWayThroughAScript, TheScriptStartsOverOnRelease) {
  // Without the reset, the second write would land at 100 ns. The reset at
  // 50..60 ns restarts the script, so it lands 100 ns after the release.
  MasterWithRam fixture{[]() -> Script {
                          co_await Wait(Picoseconds{100'000});
                          co_await Write32(0x10, 0xC0FFEE);
                        },
                        {.reset = [](LineDriver& reset) {
                          reset.WaitFor(Nanoseconds(50));
                          reset.Set(true);
                          reset.WaitFor(Nanoseconds(10));
                          reset.Set(false);
                        }}};

  fixture.platform.Run(Nanoseconds(150));
  const std::uint32_t when_it_would_have_landed = fixture.Peek32(0x10);
  fixture.platform.Run(Nanoseconds(20));
  const std::uint32_t after_the_restarted_script = fixture.Peek32(0x10);

  EXPECT_EQ(when_it_would_have_landed, 0U);
  EXPECT_EQ(after_the_restarted_script, 0xC0FFEEU);
}

TEST(WhenABusPortIsBoundToAWirePort, TheErrorNamesBothPortsAndTheirKinds) {
  Platform platform{BuiltinComponents()};
  platform.Add("cpu", "scripted_bus_master");

  EXPECT_THAT([&] { platform.Bind("cpu.socket", "cpu.irq"); },
              ThrowsMessage<std::invalid_argument>(
                  AllOf(HasSubstr("cpu.socket"), HasSubstr("cpu.irq"),
                        HasSubstr("bus"), HasSubstr("wire"))));
}

TEST(WhenResetIsPulsedWhileAScriptWaitsForTheInterrupt,
     TheScriptStartsOverOnRelease) {
  // The first write lands once at the start and once more after the reset.
  // The second never lands, because the interrupt never comes.
  MasterWithRam fixture{[]() -> Script {
                          const std::uint32_t runs = co_await Read32(0x10);
                          co_await Write32(0x10, runs + 1);
                          co_await WaitIrq();
                          co_await Write32(0x20, 0xDEAD);
                        },
                        {.irq = [](LineDriver&) {},
                         .reset =
                             [](LineDriver& reset) {
                               reset.WaitFor(Nanoseconds(10));
                               reset.Set(true);
                               reset.WaitFor(Nanoseconds(10));
                               reset.Set(false);
                             }}};

  fixture.platform.Run(Nanoseconds(30));

  EXPECT_EQ(fixture.Peek32(0x10), 2U);
  EXPECT_EQ(fixture.Peek32(0x20), 0U);
}

TEST(WhenResetIsPulsedAfterAScriptHasFinished, TheScriptPlaysAgain) {
  MasterWithRam fixture{[]() -> Script {
                          const std::uint32_t runs = co_await Read32(0x10);
                          co_await Write32(0x10, runs + 1);
                        },
                        {.reset = [](LineDriver& reset) {
                          reset.WaitFor(Nanoseconds(10));
                          reset.Set(true);
                          reset.WaitFor(Nanoseconds(10));
                          reset.Set(false);
                        }}};

  fixture.platform.Run(Nanoseconds(30));

  EXPECT_EQ(fixture.Peek32(0x10), 2U);
}

TEST(WhenAScriptWaitsForAnInterruptLineThatIsNotConnected, ItWaitsForever) {
  MasterWithRam fixture{[]() -> Script {
    co_await WaitIrq();
    co_await Write32(0x10, 0xC0FFEE);
  }};

  fixture.platform.Run(Nanoseconds(100));

  EXPECT_EQ(fixture.Peek32(0x10), 0U);
}

TEST(WhenOneResetDriverIsBoundToTwoMasters, BothAreHeldInReset) {
  Registry registry = MasterWithRam::WithLineDrivers(
      nullptr, [](LineDriver& reset) { reset.Set(true); });
  Platform platform{registry};
  for (const char* cpu : {"first", "second"}) {
    const std::string name = cpu;
    platform.Add(name, "scripted_bus_master");
    platform.Add(name + "_ram", "memory", {{"size", 0x100}});
    platform.Bind(name + ".socket", name + "_ram.socket");
    platform.ModuleAt<ScriptedBusMaster>(name).SetScript(
        []() -> Script { co_await Write32(0x10, 0xC0FFEE); });
  }
  platform.Add("reset_driver", "reset_driver");
  platform.Bind("reset_driver.line", "first.reset");
  platform.Bind("reset_driver.line", "second.reset");
  platform.Elaborate();

  platform.Run(Nanoseconds(10));

  std::uint32_t first = 1;
  std::uint32_t second = 1;
  platform.DebugRead("first.socket", 0x10,
                     std::as_writable_bytes(std::span{&first, 1}));
  platform.DebugRead("second.socket", 0x10,
                     std::as_writable_bytes(std::span{&second, 1}));
  EXPECT_EQ(first, 0U);
  EXPECT_EQ(second, 0U);
}

TEST(WhenADebugAccessIsAskedForThroughAWirePort, TheErrorSaysItIsAWire) {
  MasterWithRam fixture{nullptr, {.reset = [](LineDriver&) {}}};
  std::array<std::byte, 4> data{};

  EXPECT_THAT(
      [&] { fixture.platform.DebugRead("reset_driver.line", 0x10, data); },
      ThrowsMessage<std::invalid_argument>(HasSubstr("wire")));
}

TEST(WhenAWireConnectionIsAskedToBeTraced,
     TheErrorSaysOnlyBusConnectionsCanBe) {
  Platform platform{
      MasterWithRam::WithLineDrivers(nullptr, [](LineDriver&) {})};
  platform.Add("cpu", "scripted_bus_master");
  platform.Add("reset_driver", "reset_driver");

  EXPECT_THAT(
      [&] { platform.Bind("reset_driver.line", "cpu.reset", /*traced=*/true); },
      ThrowsMessage<std::invalid_argument>(
          AllOf(HasSubstr("bus"), HasSubstr("wire"))));
}

}  // namespace socpuppet
