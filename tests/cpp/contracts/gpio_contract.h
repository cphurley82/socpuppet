#ifndef TESTS_CPP_CONTRACTS_GPIO_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_GPIO_CONTRACT_H_

#include <cstdint>
#include <functional>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"

// What a GPIO block with the registers of SiFive's (the one in the FE310
// and the FU540) must do, whatever is behind it. This is the part that
// Zephyr's `gpio_sifive` driver and Linux's `gpio-sifive` rely on.
//
// 🎓 Each register has a bit for each of the 32 pins. A pin is an output
// while its bit in `output_en` is set, and then drives its bit in `port`;
// what is on a pin reads in `value`. Four kinds of event on an input (a
// rise, a fall, a high level and a low level) each have a register of
// pending bits and one of enable bits, and a pin's interrupt is up while
// one of its enabled events is pending.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, GpioContract,
//                                  ::testing::Types<MyGpio>);
// MyGpio must fit the GPIO slot (see socpuppet/platform/slots.h).
template <socpuppet::GpioSlot GpioType>
class GpioContract : public ::testing::Test {
 protected:
  // The registers, 32 bits each, a bit for each pin.
  static constexpr std::uint64_t kValue = 0x00;
  static constexpr std::uint64_t kOutputEnable = 0x08;
  static constexpr std::uint64_t kPort = 0x0C;
  // A pull-up holds a pin high while nothing drives it.
  static constexpr std::uint64_t kPullUp = 0x10;
  static constexpr std::uint64_t kOutputInvert = 0x40;
  // Each kind of event's enable register, with its pending register four
  // bytes on. Writing a one to a pending bit clears it.
  static constexpr std::uint64_t kRiseEnable = 0x18;
  static constexpr std::uint64_t kFallEnable = 0x20;
  static constexpr std::uint64_t kHighEnable = 0x28;
  static constexpr std::uint64_t kLowEnable = 0x30;
  static constexpr std::uint64_t Pending(std::uint64_t enable) {
    return enable + 4;
  }

  static constexpr unsigned kPins = 32;
  // How long the tests give a line to settle after a write.
  static sc_core::sc_time AMoment() { return {1, sc_core::SC_NS}; }

  // What the far end is told: a pin, and what it now drives.
  using Change = std::pair<unsigned, std::optional<bool>>;

  GpioContract() { gpio_.irq.bind(irqs_); }

  // Whether `pin`'s interrupt is up once it has settled after a write: a
  // moment on, however many delta cycles the GPIO takes over it.
  bool Interrupting(unsigned pin) {
    sc_core::wait(AMoment());
    return irqs_[pin].read();
  }

  // The pins whose interrupt is up once it has settled after a write.
  std::vector<unsigned> InterruptingPins() {
    sc_core::wait(AMoment());
    std::vector<unsigned> pins;
    for (unsigned pin = 0; pin < kPins; ++pin) {
      if (irqs_[pin].read()) pins.push_back(pin);
    }
    return pins;
  }

  // Runs `body` in a simulation thread wired to the GPIO. The run ends a
  // delta cycle after the body does, for what the GPIO does a delta on.
  void OnTheBus(const std::function<void(BusDriver&)>& body) {
    BusDriver driver{"driver", [&](BusDriver& bus) {
                       body(bus);
                       sc_core::wait(sc_core::SC_ZERO_TIME);
                       sc_core::sc_stop();
                     }};
    driver.socket.bind(gpio_.socket);
    sc_core::sc_start();
  }

  // Drives `pin` from the far end, and waits the delta cycle it takes to
  // show in the registers.
  void DriveFromTheFarEnd(unsigned pin, std::optional<bool> level) {
    gpio_.Drive(pin, level);
    sc_core::wait(sc_core::SC_ZERO_TIME);
  }

  // Keeps every change the far end is told of.
  void Listen() {
    gpio_.OnChange([this](unsigned pin, std::optional<bool> level) {
      changes_.emplace_back(pin, level);
    });
  }

  GpioType gpio_{"gpio"};
  sc_core::sc_vector<sc_core::sc_signal<bool>> irqs_{"irqs", kPins};
  std::vector<Change> changes_;
};

TYPED_TEST_SUITE_P(GpioContract);

TYPED_TEST_P(GpioContract, AnOutputPinDrivesWhatItsPortBitSays) {
  std::optional<bool> high;
  std::optional<bool> low;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kOutputEnable, 1U << 3U);
    bus.Write32(this->kPort, 1U << 3U);
    high = this->gpio_.Level(3);
    bus.Write32(this->kPort, 0);
    low = this->gpio_.Level(3);
  });

  EXPECT_EQ(high, true);
  EXPECT_EQ(low, false);
}

TYPED_TEST_P(GpioContract, AnInvertedOutputPinDrivesTheOppositeOfItsPortBit) {
  std::optional<bool> from_high;
  std::optional<bool> from_low;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kOutputInvert, 1U << 3U);
    bus.Write32(this->kOutputEnable, 1U << 3U);
    bus.Write32(this->kPort, 1U << 3U);
    from_high = this->gpio_.Level(3);
    bus.Write32(this->kPort, 0);
    from_low = this->gpio_.Level(3);
  });

  EXPECT_EQ(from_high, false);
  EXPECT_EQ(from_low, true);
}

TYPED_TEST_P(GpioContract, APinThatStopsBeingAnOutputDrivesNothing) {
  std::optional<bool> level = true;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kOutputEnable, 1U << 3U);
    bus.Write32(this->kPort, 1U << 3U);
    bus.Write32(this->kOutputEnable, 0);
    level = this->gpio_.Level(3);
  });

  EXPECT_EQ(level, std::nullopt);
}

TYPED_TEST_P(GpioContract, APinTheFarEndDrivesReadsInValue) {
  std::uint32_t high = 0;
  std::uint32_t low = ~0U;

  this->OnTheBus([&](BusDriver& bus) {
    this->DriveFromTheFarEnd(5, true);
    high = bus.Read32(this->kValue);
    this->DriveFromTheFarEnd(5, false);
    low = bus.Read32(this->kValue);
  });

  EXPECT_EQ(high, 1U << 5U);
  EXPECT_EQ(low, 0U);
}

TYPED_TEST_P(GpioContract, APinLetGoReadsHighOnceItsPullUpIsOn) {
  std::uint32_t value = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->DriveFromTheFarEnd(5, false);
    this->DriveFromTheFarEnd(5, std::nullopt);
    bus.Write32(this->kPullUp, 1U << 5U);
    value = bus.Read32(this->kValue);
  });

  EXPECT_EQ(value, 1U << 5U);
}

// 🎓 A real pin with nothing on it floats, and reads whatever it picked up
// last; this one reads low.
TYPED_TEST_P(GpioContract, APinLetGoWithNoPullUpReadsLow) {
  std::uint32_t value = ~0U;

  this->OnTheBus([&](BusDriver& bus) {
    this->DriveFromTheFarEnd(5, true);
    this->DriveFromTheFarEnd(5, std::nullopt);
    value = bus.Read32(this->kValue);
  });

  EXPECT_EQ(value, 0U);
}

// The order Zephyr's driver writes them in, when it makes an output an
// input with a pull-up.
TYPED_TEST_P(GpioContract,
             AnOutputThatBecomesAnInputWithItsPullUpOnAndNothingOnItReadsHigh) {
  std::uint32_t value = 0;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kOutputEnable, 1U << 5U);
    bus.Write32(this->kPullUp, 1U << 5U);
    bus.Write32(this->kOutputEnable, 0);
    value = bus.Read32(this->kValue);
  });

  EXPECT_EQ(value, 1U << 5U);
}

TYPED_TEST_P(GpioContract, TheFarEndIsToldOfEachChangeOfWhatAPinDrivesInOrder) {
  this->Listen();

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kOutputEnable, 1U << 3U);
    bus.Write32(this->kPort, 1U << 3U);
    bus.Write32(this->kPort, 0);
    bus.Write32(this->kOutputEnable, 0);
  });

  EXPECT_EQ(this->changes_,
            (std::vector<typename TestFixture::Change>{
                {3, false}, {3, true}, {3, false}, {3, std::nullopt}}));
}

TYPED_TEST_P(GpioContract, AWriteThatChangesNoPinTellsTheFarEndNothing) {
  this->Listen();

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kPort, 1U << 3U);
    bus.Write32(this->kOutputEnable, 1U << 3U);
    bus.Write32(this->kPort, 1U << 3U);
  });

  EXPECT_EQ(this->changes_,
            (std::vector<typename TestFixture::Change>{{3, true}}));
}

// A board's wire from one pin to another, and a script that watches the
// pins, are two listeners.
TYPED_TEST_P(GpioContract, EveryListenerIsToldOfEachChange) {
  std::vector<typename TestFixture::Change> first;
  std::vector<typename TestFixture::Change> second;
  this->gpio_.OnChange([&](unsigned pin, std::optional<bool> level) {
    first.emplace_back(pin, level);
  });
  this->gpio_.OnChange([&](unsigned pin, std::optional<bool> level) {
    second.emplace_back(pin, level);
  });

  this->OnTheBus(
      [&](BusDriver& bus) { bus.Write32(this->kOutputEnable, 1U << 3U); });

  const std::vector<typename TestFixture::Change> told{{3, false}};
  EXPECT_EQ(first, told);
  EXPECT_EQ(second, told);
}

// So that a far end that is a Python script may wait for the interpreter,
// as no CPU's process may: QBox's runs inside QEMU, which cannot wait.
TYPED_TEST_P(GpioContract, TheFarEndMayWaitWithoutHoldingUpTheWriter) {
  sc_core::sc_time written_at;
  sc_core::sc_time heard_at;
  this->gpio_.OnChange([&](unsigned, std::optional<bool>) {
    sc_core::wait(1, sc_core::SC_US);
    heard_at = sc_core::sc_time_stamp();
  });

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kOutputEnable, 1U << 3U);
    written_at = sc_core::sc_time_stamp();
    sc_core::wait(2, sc_core::SC_US);
  });

  EXPECT_EQ(written_at, sc_core::SC_ZERO_TIME);
  EXPECT_EQ(heard_at, sc_core::sc_time(1, sc_core::SC_US));
}

TYPED_TEST_P(GpioContract, APinThatIsNotThereIsNeitherDrivenNorLookedAt) {
  EXPECT_THROW(this->gpio_.Drive(this->kPins, true), std::out_of_range);
  EXPECT_THROW(this->gpio_.Level(this->kPins), std::out_of_range);
}

TYPED_TEST_P(GpioContract, AnEdgeOnAnInputIsPendingEvenThoughItIsNotEnabled) {
  std::uint32_t rises = 0;
  std::uint32_t falls = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->DriveFromTheFarEnd(5, false);
    this->DriveFromTheFarEnd(5, true);
    rises = bus.Read32(this->Pending(this->kRiseEnable));
    this->DriveFromTheFarEnd(6, true);
    this->DriveFromTheFarEnd(6, false);
    falls = bus.Read32(this->Pending(this->kFallEnable));
  });

  EXPECT_EQ(rises, 1U << 5U);
  EXPECT_EQ(falls, 1U << 6U);
}

TYPED_TEST_P(GpioContract, WritingAOneToAPendingEdgeClearsItAndNoOther) {
  std::uint32_t rises = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->DriveFromTheFarEnd(5, true);
    this->DriveFromTheFarEnd(6, true);
    bus.Write32(this->Pending(this->kRiseEnable), 1U << 5U);
    rises = bus.Read32(this->Pending(this->kRiseEnable));
  });

  EXPECT_EQ(rises, 1U << 6U);
}

// Zephyr's driver clears a pin's four pending bits in its handler, and a
// level that is still there interrupts again, which its test of level
// interrupts counts on.
TYPED_TEST_P(GpioContract,
             ALevelIsPendingAgainAsSoonAsItIsClearedWhileItHolds) {
  std::uint32_t highs = 0;
  std::uint32_t lows = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->DriveFromTheFarEnd(5, true);
    this->DriveFromTheFarEnd(6, true);
    this->DriveFromTheFarEnd(6, false);
    bus.Write32(this->Pending(this->kHighEnable), ~0U);
    bus.Write32(this->Pending(this->kLowEnable), ~0U);
    highs = bus.Read32(this->Pending(this->kHighEnable));
    lows = bus.Read32(this->Pending(this->kLowEnable));
  });

  EXPECT_EQ(highs & (1U << 5U | 1U << 6U), 1U << 5U);
  EXPECT_EQ(lows & (1U << 5U | 1U << 6U), 1U << 6U);
}

TYPED_TEST_P(GpioContract, APinsLineIsUpWhileAnEnabledEventOfItsIsPending) {
  bool pending = false;
  bool cleared = true;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kRiseEnable, 1U << 5U);
    this->DriveFromTheFarEnd(5, false);
    this->DriveFromTheFarEnd(5, true);
    pending = this->Interrupting(5);
    bus.Write32(this->Pending(this->kRiseEnable), 1U << 5U);
    cleared = this->Interrupting(5);
  });

  EXPECT_TRUE(pending);
  EXPECT_FALSE(cleared);
}

TYPED_TEST_P(GpioContract, APendingEventThatIsNotEnabledLeavesTheLineDown) {
  bool interrupting = true;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kFallEnable, 1U << 5U);
    this->DriveFromTheFarEnd(5, false);
    this->DriveFromTheFarEnd(5, true);
    interrupting = this->Interrupting(5);
  });

  EXPECT_FALSE(interrupting);
}

TYPED_TEST_P(GpioContract, AnEventOnOnePinRaisesNoOtherPinsLine) {
  std::vector<unsigned> interrupting;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kRiseEnable, ~0U);
    this->DriveFromTheFarEnd(5, true);
    interrupting = this->InterruptingPins();
  });

  EXPECT_EQ(interrupting, std::vector<unsigned>{5});
}

// Out of reset, before anything has been cleared or has changed.
TYPED_TEST_P(GpioContract, AnInputThatReadsLowIsPendingALowLevelFromTheStart) {
  std::uint32_t lows = 0;
  bool interrupting = false;

  this->OnTheBus([&](BusDriver& bus) {
    lows = bus.Read32(this->Pending(this->kLowEnable));
    bus.Write32(this->kLowEnable, 1U << 5U);
    interrupting = this->Interrupting(5);
  });

  EXPECT_TRUE(lows & (1U << 5U));
  EXPECT_TRUE(interrupting);
}

REGISTER_TYPED_TEST_SUITE_P(
    GpioContract, AnOutputPinDrivesWhatItsPortBitSays,
    AnInvertedOutputPinDrivesTheOppositeOfItsPortBit,
    APinThatStopsBeingAnOutputDrivesNothing, APinTheFarEndDrivesReadsInValue,
    APinLetGoReadsHighOnceItsPullUpIsOn, APinLetGoWithNoPullUpReadsLow,
    AnOutputThatBecomesAnInputWithItsPullUpOnAndNothingOnItReadsHigh,
    TheFarEndIsToldOfEachChangeOfWhatAPinDrivesInOrder,
    AWriteThatChangesNoPinTellsTheFarEndNothing,
    EveryListenerIsToldOfEachChange, TheFarEndMayWaitWithoutHoldingUpTheWriter,
    APinThatIsNotThereIsNeitherDrivenNorLookedAt,
    AnEdgeOnAnInputIsPendingEvenThoughItIsNotEnabled,
    WritingAOneToAPendingEdgeClearsItAndNoOther,
    ALevelIsPendingAgainAsSoonAsItIsClearedWhileItHolds,
    APinsLineIsUpWhileAnEnabledEventOfItsIsPending,
    APendingEventThatIsNotEnabledLeavesTheLineDown,
    AnEventOnOnePinRaisesNoOtherPinsLine,
    AnInputThatReadsLowIsPendingALowLevelFromTheStart);

#endif  // TESTS_CPP_CONTRACTS_GPIO_CONTRACT_H_
