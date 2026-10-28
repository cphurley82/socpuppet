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
// what is on a pin reads in `value`.
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

  static constexpr unsigned kPins = 32;

  // What the far end is told: a pin, and what it now drives.
  using Change = std::pair<unsigned, std::optional<bool>>;

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
  std::vector<Change> changes_;
};

TYPED_TEST_SUITE_P(GpioContract);

TYPED_TEST_P(GpioContract, AnOutputPinDrivesWhatItsPortBitSays) {
  std::optional<bool> high;
  std::optional<bool> low;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kOutputEnable, 1U << 3);
    bus.Write32(this->kPort, 1U << 3);
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
    bus.Write32(this->kOutputInvert, 1U << 3);
    bus.Write32(this->kOutputEnable, 1U << 3);
    bus.Write32(this->kPort, 1U << 3);
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
    bus.Write32(this->kOutputEnable, 1U << 3);
    bus.Write32(this->kPort, 1U << 3);
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

  EXPECT_EQ(high, 1U << 5);
  EXPECT_EQ(low, 0U);
}

TYPED_TEST_P(GpioContract, APinLetGoReadsHighOnceItsPullUpIsOn) {
  std::uint32_t value = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->DriveFromTheFarEnd(5, false);
    this->DriveFromTheFarEnd(5, std::nullopt);
    bus.Write32(this->kPullUp, 1U << 5);
    value = bus.Read32(this->kValue);
  });

  EXPECT_EQ(value, 1U << 5);
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
    bus.Write32(this->kOutputEnable, 1U << 5);
    bus.Write32(this->kPullUp, 1U << 5);
    bus.Write32(this->kOutputEnable, 0);
    value = bus.Read32(this->kValue);
  });

  EXPECT_EQ(value, 1U << 5);
}

TYPED_TEST_P(GpioContract, TheFarEndIsToldOfEachChangeOfWhatAPinDrivesInOrder) {
  this->Listen();

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kOutputEnable, 1U << 3);
    bus.Write32(this->kPort, 1U << 3);
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
    bus.Write32(this->kPort, 1U << 3);
    bus.Write32(this->kOutputEnable, 1U << 3);
    bus.Write32(this->kPort, 1U << 3);
  });

  EXPECT_EQ(this->changes_,
            (std::vector<typename TestFixture::Change>{{3, true}}));
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
    bus.Write32(this->kOutputEnable, 1U << 3);
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

REGISTER_TYPED_TEST_SUITE_P(
    GpioContract, AnOutputPinDrivesWhatItsPortBitSays,
    AnInvertedOutputPinDrivesTheOppositeOfItsPortBit,
    APinThatStopsBeingAnOutputDrivesNothing, APinTheFarEndDrivesReadsInValue,
    APinLetGoReadsHighOnceItsPullUpIsOn, APinLetGoWithNoPullUpReadsLow,
    AnOutputThatBecomesAnInputWithItsPullUpOnAndNothingOnItReadsHigh,
    TheFarEndIsToldOfEachChangeOfWhatAPinDrivesInOrder,
    AWriteThatChangesNoPinTellsTheFarEndNothing,
    TheFarEndMayWaitWithoutHoldingUpTheWriter,
    APinThatIsNotThereIsNeitherDrivenNorLookedAt);

#endif  // TESTS_CPP_CONTRACTS_GPIO_CONTRACT_H_
