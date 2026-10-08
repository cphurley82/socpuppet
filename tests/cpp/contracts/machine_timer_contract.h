#ifndef TESTS_CPP_CONTRACTS_MACHINE_TIMER_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_MACHINE_TIMER_CONTRACT_H_

#include <array>
#include <cstdint>
#include <functional>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"

// What every RISC-V machine timer must do, whatever is behind it. This is
// what an operating system's tick relies on.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, MachineTimerContract,
//                                  ::testing::Types<MyTimer>);
// MyTimer must fit the machine timer slot (see socpuppet/platform/slots.h).
template <socpuppet::MachineTimerSlot TimerType>
class MachineTimerContract : public ::testing::Test {
 protected:
  // The timer counts ten times a microsecond.
  static constexpr std::uint64_t kFrequency = 10'000'000;
  static constexpr std::uint64_t kTicksPerMicrosecond = 10;
  // Where the registers are, as on SiFive's CLINT. Each is 64 bits wide.
  static constexpr std::uint64_t kMtimecmp = 0x4000;
  static constexpr std::uint64_t kMtime = 0xBFF8;

  MachineTimerContract() { timer_.irq.bind(interrupt_); }

  static sc_core::sc_time Microseconds(double count) {
    return {count, sc_core::SC_US};
  }

  // Runs `body` in a simulation thread wired to the timer, and then lets
  // the simulation run on until `end`.
  void OnTheBus(std::function<void(BusDriver&)> body,
                const sc_core::sc_time& end) {
    BusDriver driver{"driver", std::move(body)};
    driver.socket.bind(timer_.socket);
    sc_core::sc_start(end);
  }

  // Reads `mtime` the way a debugger looks: in no simulated time.
  static std::uint64_t LookAtMtime(BusDriver& bus) {
    std::array<std::uint8_t, 8> bytes{};
    bus.DebugRead(kMtime, bytes);
    return socpuppet::LoadLittleEndian<std::uint64_t>(bytes);
  }

  // Waits to an absolute simulated time, for a write that must land in the
  // same delta cycle as something the timer does then.
  static void WaitUntil(BusDriver& bus, const sc_core::sc_time& when) {
    bus.WaitFor(when - sc_core::sc_time_stamp());
  }

  TimerType timer_{"timer", kFrequency};
  // A wire takes one driver, so a timer drives its line from one process
  // of its own, whether its count reached the compare value or it was
  // written to.
  sc_core::sc_signal<bool> interrupt_{"interrupt"};
};

TYPED_TEST_SUITE_P(MachineTimerContract);

TYPED_TEST_P(MachineTimerContract, LeftAloneItNeverInterrupts) {
  this->OnTheBus([](BusDriver&) {}, this->Microseconds(1000));

  EXPECT_FALSE(this->interrupt_.read());
}

TYPED_TEST_P(MachineTimerContract, MtimeCountsSimulatedTimeInTicks) {
  std::uint64_t mtime = 0;

  this->OnTheBus(
      [&](BusDriver& bus) {
        bus.WaitFor(this->Microseconds(5));
        mtime = bus.Read64(this->kMtime);
      },
      this->Microseconds(10));

  EXPECT_EQ(mtime, 5 * this->kTicksPerMicrosecond);
}

TYPED_TEST_P(MachineTimerContract, MtimeIsSeenByADebugAccess) {
  std::uint64_t mtime = 0;

  this->OnTheBus(
      [&](BusDriver& bus) {
        bus.WaitFor(this->Microseconds(5));
        mtime = this->LookAtMtime(bus);
      },
      this->Microseconds(10));

  EXPECT_EQ(mtime, 5 * this->kTicksPerMicrosecond);
}

TYPED_TEST_P(MachineTimerContract, MtimeCountsTheTimeAReaderIsAheadByAsWell) {
  std::uint64_t mtime = 0;

  this->OnTheBus(
      [&](BusDriver& bus) {
        bus.WaitFor(this->Microseconds(5));
        mtime = bus.Read64(this->kMtime, this->Microseconds(2));
      },
      this->Microseconds(10));

  EXPECT_EQ(mtime, 7 * this->kTicksPerMicrosecond);
}

TYPED_TEST_P(MachineTimerContract,
             TheInterruptRisesWhenMtimeReachesTheCompareValue) {
  bool just_before = true;
  bool just_after = false;

  this->OnTheBus(
      [&](BusDriver& bus) {
        bus.WaitFor(this->Microseconds(1));
        bus.Write64(this->kMtimecmp, 10 * this->kTicksPerMicrosecond);
        bus.WaitFor(this->Microseconds(8.9));
        just_before = this->interrupt_.read();
        bus.WaitFor(this->Microseconds(0.2));
        just_after = this->interrupt_.read();
      },
      this->Microseconds(20));

  EXPECT_FALSE(just_before);
  EXPECT_TRUE(just_after);
}

TYPED_TEST_P(MachineTimerContract, ACompareValueSetAtTheVeryStartIsHonoured) {
  this->OnTheBus(
      [&](BusDriver& bus) {
        bus.Write64(this->kMtimecmp, 10 * this->kTicksPerMicrosecond);
      },
      this->Microseconds(20));

  EXPECT_TRUE(this->interrupt_.read());
}

TYPED_TEST_P(MachineTimerContract, MovingTheCompareValueAheadEndsTheInterrupt) {
  bool after_the_move = true;

  this->OnTheBus(
      [&](BusDriver& bus) {
        bus.WaitFor(this->Microseconds(1));
        bus.Write64(this->kMtimecmp, 10 * this->kTicksPerMicrosecond);
        bus.WaitFor(this->Microseconds(14));
        // The interrupt is on by now. A tick handler does this next.
        bus.Write64(this->kMtimecmp, 100 * this->kTicksPerMicrosecond);
        bus.WaitFor(this->Microseconds(1));
        after_the_move = this->interrupt_.read();
      },
      this->Microseconds(20));

  EXPECT_FALSE(after_the_move);
}

TYPED_TEST_P(
    MachineTimerContract,
    MovingTheCompareValueAheadInTheInstantTheCountReachesItEndsTheInterrupt) {
  const sc_core::sc_time count_reaches_compare = this->Microseconds(10);
  bool after_the_move = true;

  this->OnTheBus(
      [&](BusDriver& bus) {
        bus.WaitFor(this->Microseconds(1));
        bus.Write64(this->kMtimecmp, 10 * this->kTicksPerMicrosecond);
        this->WaitUntil(bus, count_reaches_compare);
        // The timer raises its line in this very delta cycle. A tick handler
        // that runs the instant the interrupt rises writes the compare
        // register now.
        bus.Write64(this->kMtimecmp, 100 * this->kTicksPerMicrosecond);
        bus.WaitFor(this->Microseconds(1));
        after_the_move = this->interrupt_.read();
      },
      this->Microseconds(20));

  EXPECT_FALSE(after_the_move);
}

TYPED_TEST_P(MachineTimerContract, TheCompareValueCanBeWrittenInTwoHalves) {
  std::uint64_t compare = 0;

  this->OnTheBus(
      [&](BusDriver& bus) {
        bus.WaitFor(this->Microseconds(1));
        // A 32-bit CPU has to. It writes the high half as all ones first, so
        // that no value in between is one the timer would act on.
        bus.Write32(this->kMtimecmp + 4, 0xFFFF'FFFF);
        bus.Write32(this->kMtimecmp, 0x89AB'CDEF);
        bus.Write32(this->kMtimecmp + 4, 0x0123'4567);
        compare = bus.Read64(this->kMtimecmp);
      },
      this->Microseconds(10));

  EXPECT_EQ(compare, 0x0123'4567'89AB'CDEFU);
}

TYPED_TEST_P(MachineTimerContract, ACompareValueTooFarOffToEverComeIsAccepted) {
  this->OnTheBus(
      [&](BusDriver& bus) {
        bus.WaitFor(this->Microseconds(1));
        // Thousands of years ahead: more than simulated time can count to.
        bus.Write64(this->kMtimecmp, std::uint64_t{1} << 62);
      },
      this->Microseconds(1000));

  EXPECT_FALSE(this->interrupt_.read());
}

REGISTER_TYPED_TEST_SUITE_P(
    MachineTimerContract, LeftAloneItNeverInterrupts,
    MtimeCountsSimulatedTimeInTicks, MtimeIsSeenByADebugAccess,
    MtimeCountsTheTimeAReaderIsAheadByAsWell,
    TheInterruptRisesWhenMtimeReachesTheCompareValue,
    ACompareValueSetAtTheVeryStartIsHonoured,
    MovingTheCompareValueAheadEndsTheInterrupt,
    MovingTheCompareValueAheadInTheInstantTheCountReachesItEndsTheInterrupt,
    TheCompareValueCanBeWrittenInTwoHalves,
    ACompareValueTooFarOffToEverComeIsAccepted);

#endif  // TESTS_CPP_CONTRACTS_MACHINE_TIMER_CONTRACT_H_
