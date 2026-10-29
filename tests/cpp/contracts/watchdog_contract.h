#ifndef TESTS_CPP_CONTRACTS_WATCHDOG_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_WATCHDOG_CONTRACT_H_

#include <cstdint>
#include <functional>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"

// What a watchdog timer with the registers of SiFive's (the one in the
// FE310's always-on block) must do, whatever is behind it. This is the
// part that Zephyr's `wdt_sifive` driver relies on, and a boot ROM that
// has to find the watchdog off.
//
// 🎓 A watchdog is a counter that firmware has to keep setting back to
// zero ("feeding" it). Firmware that hangs stops feeding, the count
// reaches a value firmware chose, and the watchdog resets the CPU: it
// bites. This one counts ticks of a 32,768 Hz clock, the frequency of a
// watch crystal, and compares the count shifted right by a scale.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, WatchdogContract,
//                                  ::testing::Types<MyWatchdog>);
// MyWatchdog must fit the watchdog slot (see socpuppet/platform/slots.h).
template <socpuppet::WatchdogSlot WatchdogType>
class WatchdogContract : public ::testing::Test {
 protected:
  // The registers, 32 bits each.
  static constexpr std::uint64_t kConfiguration = 0x00;
  static constexpr std::uint64_t kCount = 0x08;
  // The count shifted right by the scale: what is compared.
  static constexpr std::uint64_t kScaledCount = 0x10;
  static constexpr std::uint64_t kFeed = 0x18;
  static constexpr std::uint64_t kKey = 0x1C;
  static constexpr std::uint64_t kCompare = 0x20;

  // The configuration register. The scale is its low four bits.
  static constexpr std::uint32_t kResetWhenItRunsOut = 1U << 8U;
  static constexpr std::uint32_t kZeroTheCountAtTheCompareValue = 1U << 9U;
  static constexpr std::uint32_t kAlwaysCount = 1U << 12U;
  // Count while the CPU is awake, which Zephyr's driver asks for when it is
  // told to pause the watchdog in sleep.
  static constexpr std::uint32_t kCountWhileAwake = 1U << 13U;
  // Set when the scaled count has reached the compare value. It is the
  // interrupt, and stays set until firmware clears it.
  static constexpr std::uint32_t kInterruptPending = 1U << 28U;

  // What unlocks the registers for one write, and what feeds.
  static constexpr std::uint32_t kTheKey = 0x51F15E;
  static constexpr std::uint32_t kFood = 0xD09F00D;

  // One tick of the watchdog's clock.
  static sc_core::sc_time Ticks(double count) {
    return sc_core::sc_time{count / 32768.0, sc_core::SC_SEC};
  }

  WatchdogContract() {
    watchdog_.irq.bind(irq_);
    watchdog_.bite.bind(bite_);
    bites_.line.bind(bite_);
  }

  // Runs `body` in a simulation thread wired to the watchdog. The run ends
  // when the body does: a watchdog left counting would otherwise keep the
  // simulation going.
  void OnTheBus(const std::function<void(BusDriver&)>& body) {
    BusDriver driver{"driver", [&](BusDriver& bus) {
                       body(bus);
                       sc_core::sc_stop();
                     }};
    driver.socket.bind(watchdog_.socket);
    sc_core::sc_start();
  }

  // A write to one of the watchdog's registers, as firmware has to make
  // it: the key first.
  static void Write(BusDriver& bus, std::uint64_t offset, std::uint32_t value) {
    bus.Write32(kKey, kTheKey);
    bus.Write32(offset, value);
  }

  static void Feed(BusDriver& bus) { Write(bus, kFeed, kFood); }

  // Gives the watchdog a compare value and starts it counting, with
  // whatever else of the configuration register `mode` has: what to do
  // when it runs out, and a scale. With no scale it runs out after
  // `compare` ticks.
  static void Start(BusDriver& bus, std::uint32_t compare, std::uint32_t mode) {
    Write(bus, kCompare, compare);
    Write(bus, kConfiguration, kAlwaysCount | mode);
  }

  // Half a tick to one side of a tick, so that a look lands between two
  // ticks and not on one. Each waits from where the body has got to.
  static void WaitToJustBefore(BusDriver& bus, double tick) {
    bus.WaitFor(Ticks(tick - 0.5));
  }
  static void WaitToJustAfter(BusDriver& bus, double tick) {
    bus.WaitFor(Ticks(tick + 0.5));
  }
  static void WaitATick(BusDriver& bus) { bus.WaitFor(Ticks(1)); }

  // How many times the watchdog has bitten since the simulation started.
  // A bite is a pulse, so a look at the line afterwards would miss it.
  int Bites() const { return bites_.Rises(); }

  WatchdogType watchdog_{"watchdog"};
  sc_core::sc_signal<bool> irq_{"irq"};
  sc_core::sc_signal<bool> bite_{"bite"};
  LineWatcher bites_{"bites"};
};

TYPED_TEST_SUITE_P(WatchdogContract);

// Longer than the two seconds a watchdog that came up counting would take
// to run out.
TYPED_TEST_P(WatchdogContract, LeftAloneItNeitherBitesNorInterrupts) {
  bool interrupting = true;

  this->OnTheBus([&](BusDriver& bus) {
    bus.WaitFor(this->Ticks(2 * 0xFFFF));
    interrupting = this->irq_.read();
  });

  EXPECT_EQ(this->Bites(), 0);
  EXPECT_FALSE(interrupting);
}

TYPED_TEST_P(WatchdogContract,
             StartedItBitesWhenTheCountReachesTheCompareValue) {
  int just_before = -1;
  int just_after = -1;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    this->WaitToJustBefore(bus, 100);
    just_before = this->Bites();
    this->WaitATick(bus);
    just_after = this->Bites();
  });

  EXPECT_EQ(just_before, 0);
  EXPECT_EQ(just_after, 1);
}

// A bite resets the watchdog with everything else. Firmware that starts
// again finds it as it was at power-on, and has all the time it needs to
// set it up again.
TYPED_TEST_P(WatchdogContract, AfterABiteItIsAsItWasOutOfReset) {
  std::uint32_t configuration = 0xFFFF'FFFF;
  std::uint32_t compare = 0;
  std::uint32_t count = 0xFFFF'FFFF;
  bool still_biting = true;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    bus.WaitFor(this->Ticks(150));
    configuration = bus.Read32(this->kConfiguration);
    compare = bus.Read32(this->kCompare);
    count = bus.Read32(this->kCount);
    still_biting = this->bite_.read();
  });

  EXPECT_EQ(configuration, 0U);
  EXPECT_EQ(compare, 0xFFFFU);
  EXPECT_EQ(count, 0U);
  EXPECT_FALSE(still_biting) << "the bite is a pulse, and this one never ended";
  EXPECT_EQ(this->Bites(), 1);
}

// Zero whatever the count had got to when firmware last wrote a setting,
// which is where a watchdog that works its count out on demand starts
// counting from.
TYPED_TEST_P(WatchdogContract,
             ABiteAfterASettingWasChangedPartWayLeavesTheCountAtZeroToo) {
  std::uint32_t count = 0xFFFF'FFFF;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    this->WaitToJustAfter(bus, 40);
    this->Write(bus, this->kConfiguration,
                this->kAlwaysCount | this->kResetWhenItRunsOut);
    bus.WaitFor(this->Ticks(100));
    count = bus.Read32(this->kCount);
  });

  EXPECT_EQ(count, 0U);
}

// A CPU that has just been reset is running again within the pulse of the
// bite that reset it, and may start its watchdog at once.
TYPED_TEST_P(WatchdogContract, StartedAgainWhileItIsStillBitingItBitesAgain) {
  bool still_biting = false;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    this->WaitToJustAfter(bus, 100);
    still_biting = this->bite_.read();
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    this->WaitToJustAfter(bus, 100);
  });

  ASSERT_TRUE(still_biting) << "the second start came after the pulse";
  EXPECT_EQ(this->Bites(), 2);
}

TYPED_TEST_P(WatchdogContract, FedInTimeItDoesNotBite) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    for (int feeds = 0; feeds < 5; ++feeds) {
      bus.WaitFor(this->Ticks(60));
      this->Feed(bus);
    }
    this->WaitToJustBefore(bus, 100);
  });

  EXPECT_EQ(this->Bites(), 0);
}

TYPED_TEST_P(WatchdogContract, ItBitesAFullPeriodAfterItWasLastFed) {
  int just_before = -1;
  int just_after = -1;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    bus.WaitFor(this->Ticks(60));
    this->Feed(bus);
    this->WaitToJustBefore(bus, 100);
    just_before = this->Bites();
    this->WaitATick(bus);
    just_after = this->Bites();
  });

  EXPECT_EQ(just_before, 0);
  EXPECT_EQ(just_after, 1);
}

TYPED_TEST_P(WatchdogContract, AFeedOfAnythingButTheFoodDoesNotFeed) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    bus.WaitFor(this->Ticks(60));
    this->Write(bus, this->kFeed, 0xD06F00D);
    // To where it bites if that did not feed it.
    this->WaitToJustAfter(bus, 40);
  });

  EXPECT_EQ(this->Bites(), 1);
}

TYPED_TEST_P(WatchdogContract, AWriteWithoutTheKeyIsIgnored) {
  std::uint32_t compare = 0;
  std::uint32_t configuration = 0xFFFF'FFFF;

  this->OnTheBus([&](BusDriver& bus) {
    this->Write(bus, this->kCompare, 100);
    bus.Write32(this->kCompare, 7);
    bus.Write32(this->kConfiguration,
                this->kAlwaysCount | this->kResetWhenItRunsOut);
    compare = bus.Read32(this->kCompare);
    configuration = bus.Read32(this->kConfiguration);
    bus.WaitFor(this->Ticks(150));
  });

  EXPECT_EQ(compare, 100U);
  EXPECT_EQ(configuration, 0U);
  EXPECT_EQ(this->Bites(), 0) << "it was started by a write that had no key";
}

// The key is for one write. Firmware that gave it once and wrote twice has
// made one write.
TYPED_TEST_P(WatchdogContract, TheKeyIsUsedUpByOneWrite) {
  std::uint32_t compare = 0;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kKey, this->kTheKey);
    bus.Write32(this->kCompare, 100);
    bus.Write32(this->kCompare, 7);
    compare = bus.Read32(this->kCompare);
  });

  EXPECT_EQ(compare, 100U);
}

TYPED_TEST_P(WatchdogContract,
             TheKeyRegisterReadsWhetherTheNextWriteIsUnlocked) {
  std::uint32_t unlocked = 0;
  std::uint32_t locked_again = 1;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kKey, this->kTheKey);
    unlocked = bus.Read32(this->kKey);
    bus.Write32(this->kCompare, 100);
    locked_again = bus.Read32(this->kKey);
  });

  EXPECT_EQ(unlocked, 1U);
  EXPECT_EQ(locked_again, 0U);
}

TYPED_TEST_P(WatchdogContract, AKeyOfTheWrongValueUnlocksNothing) {
  std::uint32_t compare = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Write(bus, this->kCompare, 100);
    bus.Write32(this->kKey, 0x51F15F);
    bus.Write32(this->kCompare, 7);
    compare = bus.Read32(this->kCompare);
  });

  EXPECT_EQ(compare, 100U);
}

TYPED_TEST_P(WatchdogContract, TheCompareValueIsSixteenBitsWide) {
  std::uint32_t compare = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Write(bus, this->kCompare, 0x1'0064);
    compare = bus.Read32(this->kCompare);
  });

  EXPECT_EQ(compare, 0x64U);
}

// Not told to reset, a watchdog that runs out says so and leaves it at
// that: the bit is set, the interrupt line is high, and nothing is reset.
TYPED_TEST_P(WatchdogContract,
             NotToldToResetItInterruptsWhenItRunsOutAndDoesNotBite) {
  bool interrupting_before = true;
  bool interrupting_after = false;
  std::uint32_t configuration = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, 0);
    this->WaitToJustBefore(bus, 100);
    interrupting_before = this->irq_.read();
    this->WaitATick(bus);
    interrupting_after = this->irq_.read();
    configuration = bus.Read32(this->kConfiguration);
  });

  EXPECT_FALSE(interrupting_before);
  EXPECT_TRUE(interrupting_after);
  EXPECT_EQ(this->Bites(), 0);
  EXPECT_NE(configuration & this->kInterruptPending, 0U);
}

TYPED_TEST_P(WatchdogContract, TheInterruptStaysUntilFirmwareClearsItsBit) {
  bool before_clearing = false;
  bool after_clearing = true;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kZeroTheCountAtTheCompareValue);
    bus.WaitFor(this->Ticks(150));
    before_clearing = this->irq_.read();
    // The count started over at 100 and is at 50, so it does not run out
    // again at once.
    this->Write(bus, this->kConfiguration,
                this->kAlwaysCount | this->kZeroTheCountAtTheCompareValue);
    this->WaitATick(bus);
    after_clearing = this->irq_.read();
  });

  EXPECT_TRUE(before_clearing);
  EXPECT_FALSE(after_clearing);
}

TYPED_TEST_P(WatchdogContract,
             ToldToZeroTheCountItStartsOverAtTheCompareValue) {
  std::uint32_t count = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kZeroTheCountAtTheCompareValue);
    this->WaitToJustAfter(bus, 150);
    count = bus.Read32(this->kCount);
  });

  EXPECT_EQ(count, 50U);
}

TYPED_TEST_P(WatchdogContract, ToldToZeroTheCountItStartsOverEveryPeriod) {
  std::uint32_t count = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kZeroTheCountAtTheCompareValue);
    // Nothing is written meanwhile: it starts over twice by itself.
    this->WaitToJustAfter(bus, 250);
    count = bus.Read32(this->kCount);
  });

  EXPECT_EQ(count, 50U);
}

// Firmware that had given the key and not yet used it when the watchdog
// bit has to give it again.
TYPED_TEST_P(WatchdogContract, ABiteLocksTheRegistersAgain) {
  std::uint32_t compare = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    this->WaitToJustBefore(bus, 100);
    bus.Write32(this->kKey, this->kTheKey);
    this->WaitATick(bus);
    bus.Write32(this->kCompare, 7);
    compare = bus.Read32(this->kCompare);
  });

  EXPECT_EQ(compare, 0xFFFFU);
}

TYPED_TEST_P(WatchdogContract, ToldToZeroTheCountItRunsOutAgainAPeriodLater) {
  bool before_the_second = true;
  bool after_the_second = false;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kZeroTheCountAtTheCompareValue);
    this->WaitToJustAfter(bus, 100);
    this->Write(bus, this->kConfiguration,
                this->kAlwaysCount | this->kZeroTheCountAtTheCompareValue);
    // The first has been cleared. The second is a hundred ticks after it.
    this->WaitToJustBefore(bus, 99.5);
    before_the_second = this->irq_.read();
    this->WaitATick(bus);
    after_the_second = this->irq_.read();
  });

  EXPECT_FALSE(before_the_second);
  EXPECT_TRUE(after_the_second);
}

// A compare value of zero is reached the moment the count starts over, and
// simulated time has to go on all the same.
TYPED_TEST_P(WatchdogContract,
             ToldToZeroTheCountWithACompareOfZeroItInterruptsAndTimeGoesOn) {
  bool interrupting = false;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 0, this->kZeroTheCountAtTheCompareValue);
    bus.WaitFor(this->Ticks(10));
    interrupting = this->irq_.read();
  });

  EXPECT_TRUE(interrupting);
}

TYPED_TEST_P(WatchdogContract, NotToldToZeroTheCountItCountsOn) {
  std::uint32_t count = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, 0);
    this->WaitToJustAfter(bus, 150);
    count = bus.Read32(this->kCount);
  });

  EXPECT_EQ(count, 150U);
}

// What Zephyr's driver asks for when the watchdog is to reset: both bits.
TYPED_TEST_P(WatchdogContract, ToldToResetAndToZeroTheCountItBites) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Start(
        bus, 100,
        this->kResetWhenItRunsOut | this->kZeroTheCountAtTheCompareValue);
    this->WaitToJustAfter(bus, 100);
  });

  EXPECT_EQ(this->Bites(), 1);
}

TYPED_TEST_P(WatchdogContract, ToldToCountWhileTheCpuIsAwakeItCounts) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Write(bus, this->kCompare, 100);
    this->Write(bus, this->kConfiguration,
                this->kCountWhileAwake | this->kResetWhenItRunsOut);
    this->WaitToJustAfter(bus, 100);
  });

  EXPECT_EQ(this->Bites(), 1);
}

TYPED_TEST_P(WatchdogContract, WhatIsComparedIsTheCountShiftedByTheScale) {
  constexpr std::uint32_t kScale = 3;
  std::uint32_t count = 0;
  std::uint32_t scaled = 0;
  int just_before = -1;
  int just_after = -1;

  this->OnTheBus([&](BusDriver& bus) {
    // Ten, three bits up: eighty ticks.
    this->Start(bus, 10, this->kResetWhenItRunsOut | kScale);
    this->WaitToJustBefore(bus, 80);
    count = bus.Read32(this->kCount);
    scaled = bus.Read32(this->kScaledCount);
    just_before = this->Bites();
    this->WaitATick(bus);
    just_after = this->Bites();
  });

  EXPECT_EQ(count, 79U);
  EXPECT_EQ(scaled, 9U);
  EXPECT_EQ(just_before, 0);
  EXPECT_EQ(just_after, 1);
}

TYPED_TEST_P(WatchdogContract,
             ACompareValueWrittenWhileItCountsIsTheOneItRunsOutAt) {
  int at_the_first = -1;
  int at_the_second = -1;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    this->WaitToJustAfter(bus, 40);
    this->Write(bus, this->kCompare, 200);
    bus.WaitFor(this->Ticks(100));
    at_the_first = this->Bites();
    bus.WaitFor(this->Ticks(100));
    at_the_second = this->Bites();
  });

  EXPECT_EQ(at_the_first, 0);
  EXPECT_EQ(at_the_second, 1);
}

TYPED_TEST_P(WatchdogContract,
             ACompareValueWrittenBelowTheCountRunsItOutAtOnce) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    this->WaitToJustAfter(bus, 40);
    this->Write(bus, this->kCompare, 20);
    this->WaitATick(bus);
  });

  EXPECT_EQ(this->Bites(), 1);
}

// Out of reset the compare value is the highest there is, so a watchdog
// that is started with nothing else said gives firmware two seconds.
TYPED_TEST_P(WatchdogContract, OutOfResetItsPeriodIsTheLongestItsCompareHas) {
  int just_before = -1;
  int just_after = -1;

  this->OnTheBus([&](BusDriver& bus) {
    this->Write(bus, this->kConfiguration,
                this->kAlwaysCount | this->kResetWhenItRunsOut);
    this->WaitToJustBefore(bus, 0xFFFF);
    just_before = this->Bites();
    this->WaitATick(bus);
    just_after = this->Bites();
  });

  EXPECT_EQ(just_before, 0);
  EXPECT_EQ(just_after, 1);
}

// Zephyr's driver has no way to stop this watchdog. What it does to
// "disable" it is ask for the longest period there is, which is eighteen
// hours.
TYPED_TEST_P(WatchdogContract,
             GivenTheLongestPeriodThereIsItDoesNotBiteInAnHour) {
  constexpr std::uint32_t kHighestScale = 0xF;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 0xFFFF, this->kResetWhenItRunsOut | kHighestScale);
    bus.WaitFor(sc_core::sc_time{3600, sc_core::SC_SEC});
  });

  EXPECT_EQ(this->Bites(), 0);
}

TYPED_TEST_P(WatchdogContract, StoppedItKeepsItsCountAndDoesNotRunOut) {
  std::uint32_t count = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Start(bus, 100, this->kResetWhenItRunsOut);
    this->WaitToJustAfter(bus, 40);
    this->Write(bus, this->kConfiguration, this->kResetWhenItRunsOut);
    bus.WaitFor(this->Ticks(200));
    count = bus.Read32(this->kCount);
  });

  EXPECT_EQ(count, 40U);
  EXPECT_EQ(this->Bites(), 0);
}

REGISTER_TYPED_TEST_SUITE_P(
    WatchdogContract, LeftAloneItNeitherBitesNorInterrupts,
    StartedItBitesWhenTheCountReachesTheCompareValue,
    AfterABiteItIsAsItWasOutOfReset,
    ABiteAfterASettingWasChangedPartWayLeavesTheCountAtZeroToo,
    StartedAgainWhileItIsStillBitingItBitesAgain, FedInTimeItDoesNotBite,
    ItBitesAFullPeriodAfterItWasLastFed, AFeedOfAnythingButTheFoodDoesNotFeed,
    AWriteWithoutTheKeyIsIgnored, TheKeyIsUsedUpByOneWrite,
    TheKeyRegisterReadsWhetherTheNextWriteIsUnlocked,
    AKeyOfTheWrongValueUnlocksNothing, TheCompareValueIsSixteenBitsWide,
    NotToldToResetItInterruptsWhenItRunsOutAndDoesNotBite,
    TheInterruptStaysUntilFirmwareClearsItsBit,
    ToldToZeroTheCountItStartsOverAtTheCompareValue,
    ToldToZeroTheCountItStartsOverEveryPeriod, ABiteLocksTheRegistersAgain,
    ToldToZeroTheCountItRunsOutAgainAPeriodLater,
    ToldToZeroTheCountWithACompareOfZeroItInterruptsAndTimeGoesOn,
    NotToldToZeroTheCountItCountsOn, ToldToResetAndToZeroTheCountItBites,
    ToldToCountWhileTheCpuIsAwakeItCounts,
    WhatIsComparedIsTheCountShiftedByTheScale,
    ACompareValueWrittenWhileItCountsIsTheOneItRunsOutAt,
    ACompareValueWrittenBelowTheCountRunsItOutAtOnce,
    OutOfResetItsPeriodIsTheLongestItsCompareHas,
    GivenTheLongestPeriodThereIsItDoesNotBiteInAnHour,
    StoppedItKeepsItsCountAndDoesNotRunOut);

#endif  // TESTS_CPP_CONTRACTS_WATCHDOG_CONTRACT_H_
