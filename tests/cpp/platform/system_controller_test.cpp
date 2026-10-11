#include "socpuppet/models/system_controller.h"

#include <array>
#include <cstdint>
#include <functional>
#include <span>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "socpuppet/regs/system_controller.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_driver.h"
#include "tests/cpp/support/riscv_program.h"
#include "tests/cpp/support/test_components.h"

// What the system controller does with its wires and with time. What its
// registers mean is held without a simulator, in
// tests/cpp/unit/system_controller_logic_test.cpp.

namespace {

constexpr std::uint32_t kDie = 3;
constexpr std::uint32_t kBootAddress = 0x1020'0000;

sc_core::sc_time Nanoseconds(double count) { return {count, sc_core::SC_NS}; }

// A CPU's clock on a socpuppet board ticks every 100 ns, and a reset
// shorter than a tick is one a CPU need not see.
const sc_core::sc_time kOneTickOfACpu = Nanoseconds(100);
// Long enough for a program of a few instructions to have run, been reset
// and run again, whatever reset it.
const sc_core::sc_time kTimeToStartTwice{1, sc_core::SC_MS};
// Far longer than any pulse: a reset still high by then is stuck.
const sc_core::sc_time kLongAfter{1, sc_core::SC_MS};

// A system controller with its three lines in a test's hands, and a test's
// thread on its bus. The thread drives `hold` and `bite` and reads `reset`.
struct Rig {
  explicit Rig(std::function<void(Rig&, BusDriver&)> body)
      : driver{"driver", [this, body = std::move(body)](BusDriver& bus) {
                 body(*this, bus);
               }} {
    controller.hold.bind(hold);
    controller.bite.bind(bite);
    controller.reset.bind(reset);
    driver.socket.bind(controller.socket);
    sc_core::sc_start();
  }

  // Lets the controller do what a change of a line asks of it. A wire
  // written in one delta cycle is read by its listener in the next, and
  // what the listener writes is read in the one after.
  static void LetItSettle() { sc_core::wait(Nanoseconds(1)); }

  socpuppet::SystemController controller{"controller", kDie, kBootAddress};
  sc_core::sc_signal<bool> hold{"hold"};
  sc_core::sc_signal<bool> bite{"bite"};
  sc_core::sc_signal<bool> reset{"reset"};
  BusDriver driver;
};

// A CPU whose reset is its system controller's to drive, with a RAM for
// its program. `bite` drives the controller's watchdog line. With none,
// nothing is connected to that line, and nothing ever is to `hold`.
struct CpuUnderASystemController {
  static constexpr std::uint64_t kRam = 0x8000'0000;
  static constexpr std::uint64_t kController = 0x10'0000;

  explicit CpuUnderASystemController(
      const Drive& bite = nullptr,
      const sc_core::sc_time& quantum = sc_core::SC_ZERO_TIME)
      : platform{WithALineDriver(bite)} {
    platform.SetQuantum(quantum);
    platform.Add("cpu", "dbt_rise_cpu", {{"xlen", 64}, {"reset_vector", kRam}});
    platform.Add("bus", "router",
                 {{"outputs", 2},
                  {"out0.base", kRam},
                  {"out0.size", 0x1000},
                  {"out1.base", kController},
                  {"out1.size", SYSTEM_CONTROLLER_SIZE}});
    platform.Add("ram", "memory", {{"size", 0x1000}});
    platform.Add("syscon", "system_controller",
                 {{"die", kDie}, {"boot_address", kBootAddress}});
    platform.Bind("cpu.socket", "bus.target");
    platform.Bind("bus.out0", "ram.socket");
    platform.Bind("bus.out1", "syscon.socket");
    if (bite) {
      platform.Add("watchdog", "line_driver");
      platform.Bind("watchdog.line", "syscon.bite");
    }
    platform.Bind("syscon.reset", "cpu.reset");
    platform.Elaborate();
  }

  static socpuppet::Registry WithALineDriver(const Drive& bite) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    AddLineDriver(registry, "line_driver", bite);
    return registry;
  }

  void Load(const riscv::Program& program) {
    platform.DebugWrite("cpu.socket", kRam, std::as_bytes(std::span{program}));
  }

  // A register of the controller's, as a debugger sees it.
  std::uint32_t Register(std::uint64_t offset) {
    std::array<std::uint8_t, 4> word{};
    platform.DebugRead("cpu.socket", kController + offset,
                       std::as_writable_bytes(std::span{word}));
    return socpuppet::LoadLittleEndian<std::uint32_t>(word);
  }

  // How many times a CountStartsThen program has been started.
  std::uint32_t Starts() {
    std::array<std::uint8_t, 4> word{};
    platform.DebugRead("cpu.socket", kRam + riscv::kResultOffset,
                       std::as_writable_bytes(std::span{word}));
    return socpuppet::LoadLittleEndian<std::uint32_t>(word);
  }

  socpuppet::Platform platform;
};

}  // namespace

// Nothing is connected to either of the controller's inputs here: a CPU
// with no watchdog and nothing to hold it has a system controller all the
// same.
TEST(ASystemControllerOnAPlatform, ReadsWhatThePlatformBuiltItWith) {
  CpuUnderASystemController board;

  EXPECT_EQ(board.Register(SYSTEM_CONTROLLER_DIE), kDie);
  EXPECT_EQ(board.Register(SYSTEM_CONTROLLER_BOOT_ADDRESS), kBootAddress);
}

TEST(WhenACpuAsksItsSystemControllerForAReset, ItStartsOverAtItsResetVector) {
  CpuUnderASystemController board;
  board.Load(riscv::CountStartsThen(
      /*sleep=*/true, CpuUnderASystemController::kController +
                          SYSTEM_CONTROLLER_RESET_REQUEST));

  board.platform.Run(kTimeToStartTwice);

  EXPECT_EQ(board.Starts(), 2U);
}

// A watchdog bites when it bites, and a CPU that is busy may be running
// well ahead of the simulation's clock by then: here by up to 100 us,
// against a pulse of the reset that lasts one. The bite comes at 250 us,
// half way between two of the CPU's looks at its inputs, so that the whole
// pulse is over before the next. The line then stays high, which is one
// bite and not a reset for every moment of it: the CPU starts twice.
class WhenTheWatchdogBitesACpu : public ::testing::TestWithParam<bool> {};

TEST_P(WhenTheWatchdogBitesACpu, ItStartsOverAtItsResetVector) {
  const bool asleep = GetParam();
  CpuUnderASystemController board{[](LineDriver& bite) {
                                    bite.WaitFor({250, sc_core::SC_US});
                                    bite.Set(true);
                                  },
                                  /*quantum=*/{100, sc_core::SC_US}};
  board.Load(riscv::CountStartsThen(asleep));

  board.platform.Run(kTimeToStartTwice);

  EXPECT_EQ(board.Starts(), 2U);
}

INSTANTIATE_TEST_SUITE_P(, WhenTheWatchdogBitesACpu, ::testing::Bool(),
                         [](const auto& asleep) {
                           return asleep.param ? "ThatIsAsleep" : "ThatIsBusy";
                         });

TEST(ASystemControllersResetLine, FollowsItsHoldLine) {
  bool while_held = false;
  bool once_let_go = true;

  Rig rig{[&](Rig& lines, BusDriver&) {
    lines.hold.write(true);
    Rig::LetItSettle();
    while_held = lines.reset.read();
    lines.hold.write(false);
    Rig::LetItSettle();
    once_let_go = lines.reset.read();
  }};

  EXPECT_TRUE(while_held);
  EXPECT_FALSE(once_let_go);
}

TEST(WhenTheWatchdogsLineRises, ASystemControllerPulsesItsResetLine) {
  bool at_once = false;
  bool a_tick_later = false;
  bool long_after = true;

  Rig rig{[&](Rig& lines, BusDriver&) {
    lines.bite.write(true);
    Rig::LetItSettle();
    at_once = lines.reset.read();
    sc_core::wait(kOneTickOfACpu);
    a_tick_later = lines.reset.read();
    sc_core::wait(kLongAfter);
    long_after = lines.reset.read();
  }};

  EXPECT_TRUE(at_once);
  EXPECT_TRUE(a_tick_later) << "the pulse was shorter than a CPU's tick";
  EXPECT_FALSE(long_after) << "the reset never fell";
}

TEST(WhenTheWatchdogsLineRises, TheCpuReadsThatTheWatchdogResetIt) {
  std::uint32_t cause = 0xAAAA'AAAA;

  Rig rig{[&](Rig& lines, BusDriver& bus) {
    lines.bite.write(true);
    Rig::LetItSettle();
    cause = bus.Read32(SYSTEM_CONTROLLER_RESET_CAUSE);
  }};

  EXPECT_EQ(cause, SYSTEM_CONTROLLER_RESET_CAUSE_WATCHDOG);
}

TEST(WhenTheWatchdogsLineFalls, ASystemControllerResetsNothing) {
  bool after_the_fall = true;

  Rig rig{[&](Rig& lines, BusDriver&) {
    lines.bite.write(true);
    sc_core::wait(kLongAfter);
    lines.bite.write(false);
    Rig::LetItSettle();
    after_the_fall = lines.reset.read();
  }};

  EXPECT_FALSE(after_the_fall);
}

TEST(WhenACpuWritesAOneToTheResetRequest, ASystemControllerPulsesItsResetLine) {
  bool at_once = false;
  bool a_tick_later = false;
  bool long_after = true;

  Rig rig{[&](Rig& lines, BusDriver& bus) {
    bus.Write32(SYSTEM_CONTROLLER_RESET_REQUEST,
                SYSTEM_CONTROLLER_RESET_REQUEST_RESET);
    Rig::LetItSettle();
    at_once = lines.reset.read();
    sc_core::wait(kOneTickOfACpu);
    a_tick_later = lines.reset.read();
    sc_core::wait(kLongAfter);
    long_after = lines.reset.read();
  }};

  EXPECT_TRUE(at_once);
  EXPECT_TRUE(a_tick_later) << "the pulse was shorter than a CPU's tick";
  EXPECT_FALSE(long_after) << "the reset never fell";
}

TEST(ASystemControllersRegisters, AreAnsweredOnItsSocket) {
  std::uint32_t die = 0;
  std::uint32_t boot_address = 0;

  Rig rig{[&](Rig&, BusDriver& bus) {
    die = bus.Read32(SYSTEM_CONTROLLER_DIE);
    boot_address = bus.Read32(SYSTEM_CONTROLLER_BOOT_ADDRESS);
  }};

  EXPECT_EQ(die, kDie);
  EXPECT_EQ(boot_address, kBootAddress);
}

TEST(WhenASystemControllerRefusesAnAccess, TheBusSeesAnAddressError) {
  tlm::tlm_response_status beside = tlm::TLM_OK_RESPONSE;
  tlm::tlm_response_status not_firmwares_to_write = tlm::TLM_OK_RESPONSE;

  Rig rig{[&](Rig&, BusDriver& bus) {
    std::array<std::uint8_t, 4> word{};
    beside = bus.Read(SYSTEM_CONTROLLER_RESET_REQUEST + 4, word);
    not_firmwares_to_write = bus.Write32(SYSTEM_CONTROLLER_DIE, 7);
  }};

  EXPECT_EQ(beside, tlm::TLM_ADDRESS_ERROR_RESPONSE);
  EXPECT_EQ(not_firmwares_to_write, tlm::TLM_ADDRESS_ERROR_RESPONSE);
}

// A reset is one pulse however many reasons there are for it: of two that
// come within a pulse of each other, the second does not make it longer.
TEST(WhenACpuAsksForAResetWhileTheWatchdogsPulseIsUnderWay,
     TheResetFallsWhenTheFirstPulseEnds) {
  const sc_core::sc_time half_a_pulse = Nanoseconds(500);
  bool during_the_first = false;
  bool after_the_first = true;

  Rig rig{[&](Rig& lines, BusDriver& bus) {
    lines.bite.write(true);
    sc_core::wait(half_a_pulse);
    during_the_first = lines.reset.read();
    bus.Write32(SYSTEM_CONTROLLER_RESET_REQUEST,
                SYSTEM_CONTROLLER_RESET_REQUEST_RESET);
    // To where the first pulse has ended, and one that started at the
    // request would not have.
    sc_core::wait(half_a_pulse + Nanoseconds(100));
    after_the_first = lines.reset.read();
  }};

  EXPECT_TRUE(during_the_first);
  EXPECT_FALSE(after_the_first);
}

// A debugger looks and does not touch: its read is answered, and its write
// to the register that asks for a reset asks for nothing.
TEST(ADebugAccessToASystemController, ReadsARegisterAndResetsNothing) {
  std::array<std::uint8_t, 4> seen{};
  unsigned read = 0;
  unsigned written = 4;
  bool reset_after = true;

  Rig rig{[&](Rig& lines, BusDriver& bus) {
    read = bus.DebugRead(SYSTEM_CONTROLLER_BOOT_ADDRESS, seen);
    written = bus.DebugWrite(SYSTEM_CONTROLLER_RESET_REQUEST,
                             socpuppet::LittleEndianBytes(std::uint32_t{
                                 SYSTEM_CONTROLLER_RESET_REQUEST_RESET}));
    Rig::LetItSettle();
    reset_after = lines.reset.read();
  }};

  EXPECT_EQ(read, 4U);
  EXPECT_EQ(socpuppet::LoadLittleEndian<std::uint32_t>(seen), kBootAddress);
  EXPECT_EQ(written, 0U);
  EXPECT_FALSE(reset_after);
}
