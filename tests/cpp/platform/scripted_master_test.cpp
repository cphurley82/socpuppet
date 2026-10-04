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

using namespace socpuppet;
using ::testing::AllOf;
using ::testing::HasSubstr;
using ::testing::ThrowsMessage;

namespace {

const sc_core::sc_time ns{1, sc_core::SC_NS};

// Drives one wire from a test: `body` runs in a simulation thread and can
// set the line and wait.
class LineDriver : public sc_core::sc_module {
 public:
  sc_core::sc_out<bool> line{"line"};

  LineDriver(const sc_core::sc_module_name& name, std::function<void(LineDriver&)> body)
      : sc_module(name), body_(std::move(body)) {
    SC_THREAD(run);
  }

  void set(bool level) { line.write(level); }
  void wait_for(const sc_core::sc_time& duration) { wait(duration); }

 private:
  void run() { body_(*this); }
  std::function<void(LineDriver&)> body_;
};

using Drive = std::function<void(LineDriver&)>;

// What drives a master's input lines in a test. A line with no driver is
// left unconnected.
struct Lines {
  Drive irq;
  Drive reset;
};

// A scripted bus master wired straight to a 0x100-byte RAM.
struct MasterWithRam {
  explicit MasterWithRam(std::function<Script()> script, Lines lines = {})
      : platform{with_line_drivers(lines.irq, lines.reset)} {
    const Drive& irq = lines.irq;
    const Drive& reset = lines.reset;
    platform.add("cpu", "scripted_bus_master");
    platform.add("ram", "memory", {{"size", 0x100}});
    platform.bind("cpu.socket", "ram.socket");
    if (irq) {
      platform.add("irq_driver", "irq_driver");
      platform.bind("irq_driver.line", "cpu.irq");
    }
    if (reset) {
      platform.add("reset_driver", "reset_driver");
      platform.bind("reset_driver.line", "cpu.reset");
    }
    platform.module<ScriptedBusMaster>("cpu").set_script(std::move(script));
    platform.elaborate();
  }

  std::uint32_t peek32(std::uint64_t address) {
    std::uint32_t value = 0;
    platform.debug_read("cpu.socket", address, std::as_writable_bytes(std::span{&value, 1}));
    return value;
  }

  static Registry with_line_drivers(Drive irq, Drive reset) {
    Registry registry = builtin_components();
    for (const auto& [implementation, body] : {std::pair{"irq_driver", irq},
                                               std::pair{"reset_driver", reset}}) {
      registry.add(implementation, [body](const char* name, const Config&) {
        auto module = std::make_unique<LineDriver>(name, body);
        std::vector<Port> ports{wire_source_port("line", module->line)};
        return Instance{std::move(module), std::move(ports)};
      });
    }
    return registry;
  }

  Platform platform;
};

}  // namespace

TEST(WhenAScriptReadsAnAddressItWroteEarlier, TheReadReturnsTheWrittenValue) {
  MasterWithRam fixture{[]() -> Script {
    co_await write32(0x10, 0xC0FFEE);
    const std::uint32_t read_back = co_await read32(0x10);
    co_await write32(0x20, read_back);
  }};

  fixture.platform.run();

  EXPECT_EQ(fixture.peek32(0x20), 0xC0FFEEu);
}

TEST(WhenAScriptWaits, ItsNextOpHappensThatMuchLater) {
  MasterWithRam fixture{[]() -> Script {
    co_await wait_for(Picoseconds{10'000});
    co_await write32(0x10, 0xC0FFEE);
  }};

  fixture.platform.run(9 * ns);
  const std::uint32_t before = fixture.peek32(0x10);
  fixture.platform.run(2 * ns);
  const std::uint32_t after = fixture.peek32(0x10);

  EXPECT_EQ(before, 0u);
  EXPECT_EQ(after, 0xC0FFEEu);
}

TEST(WhenAnExpectedValueIsNotTheOneInMemory, TheRunFailsNamingAddressExpectedAndActual) {
  MasterWithRam fixture{[]() -> Script {
    co_await write32(0x10, 0xBAD);
    co_await expect32(0x10, 0xC0FFEE);
  }};

  EXPECT_THAT([&] { fixture.platform.run(); },
              ThrowsMessage<ExpectationFailed>(
                  AllOf(HasSubstr("0x10"), HasSubstr("0xc0ffee"), HasSubstr("0xbad"))));
}

TEST(WhenAnExpectedValueIsNotTheOneInMemory, TheScriptDoesNotCarryOn) {
  MasterWithRam fixture{[]() -> Script {
    co_await expect32(0x10, 0xC0FFEE);
    co_await write32(0x20, 1);
  }};

  EXPECT_THROW(fixture.platform.run(), ExpectationFailed);

  EXPECT_EQ(fixture.peek32(0x20), 0u);
}

TEST(WhenAScriptWaitsForTheInterrupt, ItCarriesOnOnceTheLineRises) {
  MasterWithRam fixture{[]() -> Script {
                          co_await wait_irq();
                          co_await write32(0x10, 0xC0FFEE);
                        },
                        {.irq = [](LineDriver& irq) {
                           irq.wait_for(10 * ns);
                           irq.set(true);
                         }}};

  fixture.platform.run(9 * ns);
  const std::uint32_t before = fixture.peek32(0x10);
  fixture.platform.run(2 * ns);
  const std::uint32_t after = fixture.peek32(0x10);

  EXPECT_EQ(before, 0u);
  EXPECT_EQ(after, 0xC0FFEEu);
}

TEST(WhenResetIsHeldFromTimeZero, TheScriptStartsOnlyOnceItIsReleased) {
  MasterWithRam fixture{[]() -> Script { co_await write32(0x10, 0xC0FFEE); },
                        {.reset = [](LineDriver& reset) {
                           reset.set(true);
                           reset.wait_for(10 * ns);
                           reset.set(false);
                         }}};

  fixture.platform.run(9 * ns);
  const std::uint32_t during_reset = fixture.peek32(0x10);
  fixture.platform.run(2 * ns);
  const std::uint32_t after_release = fixture.peek32(0x10);

  EXPECT_EQ(during_reset, 0u);
  EXPECT_EQ(after_release, 0xC0FFEEu);
}

TEST(WhenResetIsPulsedPartWayThroughAScript, TheScriptStartsOverOnRelease) {
  // Without the reset, the second write would land at 100 ns. The reset at
  // 50..60 ns restarts the script, so it lands 100 ns after the release.
  MasterWithRam fixture{[]() -> Script {
                          co_await wait_for(Picoseconds{100'000});
                          co_await write32(0x10, 0xC0FFEE);
                        },
                        {.reset = [](LineDriver& reset) {
                           reset.wait_for(50 * ns);
                           reset.set(true);
                           reset.wait_for(10 * ns);
                           reset.set(false);
                         }}};

  fixture.platform.run(150 * ns);
  const std::uint32_t when_it_would_have_landed = fixture.peek32(0x10);
  fixture.platform.run(20 * ns);
  const std::uint32_t after_the_restarted_script = fixture.peek32(0x10);

  EXPECT_EQ(when_it_would_have_landed, 0u);
  EXPECT_EQ(after_the_restarted_script, 0xC0FFEEu);
}

TEST(WhenABusPortIsBoundToAWirePort, TheErrorNamesBothPortsAndTheirKinds) {
  Platform platform{builtin_components()};
  platform.add("cpu", "scripted_bus_master");

  EXPECT_THAT([&] { platform.bind("cpu.socket", "cpu.irq"); },
              ThrowsMessage<std::invalid_argument>(AllOf(
                  HasSubstr("cpu.socket"), HasSubstr("cpu.irq"), HasSubstr("bus"),
                  HasSubstr("wire"))));
}

TEST(WhenResetIsPulsedWhileAScriptWaitsForTheInterrupt, TheScriptStartsOverOnRelease) {
  // The first write lands once at the start and once more after the reset.
  // The second never lands, because the interrupt never comes.
  MasterWithRam fixture{[]() -> Script {
                          const std::uint32_t runs = co_await read32(0x10);
                          co_await write32(0x10, runs + 1);
                          co_await wait_irq();
                          co_await write32(0x20, 0xDEAD);
                        },
                        {.irq = [](LineDriver&) {},
                         .reset = [](LineDriver& reset) {
                           reset.wait_for(10 * ns);
                           reset.set(true);
                           reset.wait_for(10 * ns);
                           reset.set(false);
                         }}};

  fixture.platform.run(30 * ns);

  EXPECT_EQ(fixture.peek32(0x10), 2u);
  EXPECT_EQ(fixture.peek32(0x20), 0u);
}

TEST(WhenResetIsPulsedAfterAScriptHasFinished, TheScriptPlaysAgain) {
  MasterWithRam fixture{[]() -> Script {
                          const std::uint32_t runs = co_await read32(0x10);
                          co_await write32(0x10, runs + 1);
                        },
                        {.reset = [](LineDriver& reset) {
                           reset.wait_for(10 * ns);
                           reset.set(true);
                           reset.wait_for(10 * ns);
                           reset.set(false);
                         }}};

  fixture.platform.run(30 * ns);

  EXPECT_EQ(fixture.peek32(0x10), 2u);
}

TEST(WhenAScriptWaitsForAnInterruptLineThatIsNotConnected, ItWaitsForever) {
  MasterWithRam fixture{[]() -> Script {
    co_await wait_irq();
    co_await write32(0x10, 0xC0FFEE);
  }};

  fixture.platform.run(100 * ns);

  EXPECT_EQ(fixture.peek32(0x10), 0u);
}

TEST(WhenOneResetDriverIsBoundToTwoMasters, BothAreHeldInReset) {
  Registry registry = MasterWithRam::with_line_drivers(nullptr, [](LineDriver& reset) {
    reset.set(true);
  });
  Platform platform{registry};
  for (const char* cpu : {"first", "second"}) {
    const std::string name = cpu;
    platform.add(name, "scripted_bus_master");
    platform.add(name + "_ram", "memory", {{"size", 0x100}});
    platform.bind(name + ".socket", name + "_ram.socket");
    platform.module<ScriptedBusMaster>(name).set_script(
        []() -> Script { co_await write32(0x10, 0xC0FFEE); });
  }
  platform.add("reset_driver", "reset_driver");
  platform.bind("reset_driver.line", "first.reset");
  platform.bind("reset_driver.line", "second.reset");
  platform.elaborate();

  platform.run(10 * ns);

  std::uint32_t first = 1, second = 1;
  platform.debug_read("first.socket", 0x10, std::as_writable_bytes(std::span{&first, 1}));
  platform.debug_read("second.socket", 0x10, std::as_writable_bytes(std::span{&second, 1}));
  EXPECT_EQ(first, 0u);
  EXPECT_EQ(second, 0u);
}

TEST(WhenADebugAccessIsAskedForThroughAWirePort, TheErrorSaysItIsAWire) {
  MasterWithRam fixture{nullptr, {.reset = [](LineDriver&) {}}};
  std::array<std::byte, 4> data{};

  EXPECT_THAT([&] { fixture.platform.debug_read("reset_driver.line", 0x10, data); },
              ThrowsMessage<std::invalid_argument>(HasSubstr("wire")));
}
