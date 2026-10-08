#ifndef TESTS_CPP_CONTRACTS_INTERRUPT_CONTROLLER_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_INTERRUPT_CONTROLLER_CONTRACT_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <functional>
#include <utility>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/platform/slots.h"
#include "tests/cpp/contracts/bus_driver.h"

// What every RISC-V platform-level interrupt controller (PLIC) must do,
// whatever is behind it. This is what an operating system's interrupt
// handling relies on, for one CPU in machine mode.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, InterruptControllerContract,
//                                  ::testing::Types<MyPlic>);
// MyPlic must fit the interrupt controller slot (see
// socpuppet/platform/slots.h) and have at least 31 sources.
template <socpuppet::InterruptControllerSlot ControllerType>
class InterruptControllerContract : public ::testing::Test {
 protected:
  // The PLIC's registers, 32 bits each. Sources are numbered from 1.
  static constexpr std::uint64_t Priority(unsigned source) {
    return std::uint64_t{4} * source;
  }
  // One bit per source: whether it may interrupt the CPU.
  static constexpr std::uint64_t kEnable = 0x2000;
  // Only sources with a priority above this interrupt.
  static constexpr std::uint64_t kThreshold = 0x20'0000;
  // Read to claim the interrupt, write the source back to complete it.
  static constexpr std::uint64_t kClaimComplete = 0x20'0004;

  static constexpr unsigned kLastSource = 31;

  InterruptControllerContract() {
    for (unsigned source = 1; source <= kLastSource; ++source) {
      // Only the lines a test drives are connected.
      if (source == 3 || source == 5 || source == kLastSource) {
        controller_.sources[source - 1].bind(lines_[source]);
      }
    }
    controller_.irq.bind(interrupt_);
  }

  // Runs `body` in a simulation thread wired to the controller, to
  // completion, and then lets what it set in motion settle.
  void OnTheBus(const std::function<void(BusDriver&)>& body) {
    BusDriver driver{"driver", [&](BusDriver& bus) {
                       body(bus);
                       Settle(bus);
                     }};
    driver.socket.bind(controller_.socket);
    sc_core::sc_start();
  }

  // Lets a change to a line, and what follows from it, happen.
  static void Settle(BusDriver& bus) {
    bus.WaitFor(sc_core::sc_time{1, sc_core::SC_NS});
  }

  static std::uint32_t Read(BusDriver& bus, std::uint64_t address) {
    std::array<std::uint8_t, 4> bytes{};
    bus.Read(address, bytes);
    std::uint32_t value = 0;
    std::memcpy(&value, bytes.data(), sizeof value);
    return value;
  }

  static void Write(BusDriver& bus, std::uint64_t address,
                    std::uint32_t value) {
    std::array<std::uint8_t, 4> bytes{};
    std::memcpy(bytes.data(), &value, sizeof value);
    bus.Write(address, bytes);
  }

  // Gives `source` a priority and lets it interrupt the CPU.
  void Enable(BusDriver& bus, unsigned source, std::uint32_t priority) {
    Write(bus, Priority(source), priority);
    Write(bus, kEnable, Read(bus, kEnable) | (std::uint32_t{1} << source));
  }

  void Raise(BusDriver& bus, unsigned source) {
    lines_[source].write(true);
    Settle(bus);
  }
  void Lower(BusDriver& bus, unsigned source) {
    lines_[source].write(false);
    Settle(bus);
  }
  // Raises `source` and returns in the delta cycle in which the controller
  // sees the new level, so that whatever the caller does next lands in
  // that same delta cycle. A line takes its level a delta cycle after it is
  // written; Raise, by contrast, lets time pass.
  void RaiseWithoutSettling(BusDriver& bus, unsigned source) {
    lines_[source].write(true);
    bus.WaitFor(sc_core::SC_ZERO_TIME);
  }

  ControllerType controller_{"controller"};
  // The lines of the sources, by source number. Entry 0 is unused.
  sc_core::sc_vector<sc_core::sc_signal<bool>> lines_{"line", kLastSource + 1};
  // A wire takes one driver, so a controller drives its output from one
  // process of its own, however many of its processes change its mind.
  sc_core::sc_signal<bool> interrupt_{"interrupt"};
};

TYPED_TEST_SUITE_P(InterruptControllerContract);

TYPED_TEST_P(InterruptControllerContract,
             AnEnabledSourceWithAPriorityInterruptsWhenItsLineRises) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Enable(bus, 3, /*priority=*/1);
    this->Raise(bus, 3);
  });

  EXPECT_TRUE(this->interrupt_.read());
}

TYPED_TEST_P(InterruptControllerContract, ASourceThatIsNotEnabledDoesNot) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Write(bus, this->Priority(3), 1);
    this->Raise(bus, 3);
  });

  EXPECT_FALSE(this->interrupt_.read());
}

TYPED_TEST_P(InterruptControllerContract,
             ASourceWhosePriorityIsNotAboveTheThresholdDoesNot) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Write(bus, this->kThreshold, 2);
    this->Enable(bus, 3, /*priority=*/2);
    this->Raise(bus, 3);
  });

  EXPECT_FALSE(this->interrupt_.read());
}

TYPED_TEST_P(InterruptControllerContract,
             ASourceEnabledWhileItsLineIsAlreadyHighInterrupts) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Raise(bus, 3);
    this->Enable(bus, 3, /*priority=*/1);
  });

  EXPECT_TRUE(this->interrupt_.read());
}

TYPED_TEST_P(InterruptControllerContract,
             AClaimSaysWhichSourceItWasAndEndsTheInterrupt) {
  std::uint32_t claimed = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Enable(bus, 3, /*priority=*/1);
    this->Raise(bus, 3);
    claimed = this->Read(bus, this->kClaimComplete);
  });

  EXPECT_EQ(claimed, 3U);
  EXPECT_FALSE(this->interrupt_.read());
}

TYPED_TEST_P(InterruptControllerContract,
             OfTwoSourcesTheOneWithTheHigherPriorityIsClaimedFirst) {
  std::uint32_t first = 0;
  std::uint32_t second = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Enable(bus, 3, /*priority=*/1);
    this->Enable(bus, 5, /*priority=*/2);
    this->Raise(bus, 3);
    this->Raise(bus, 5);
    first = this->Read(bus, this->kClaimComplete);
    second = this->Read(bus, this->kClaimComplete);
  });

  EXPECT_EQ(first, 5U);
  EXPECT_EQ(second, 3U);
}

TYPED_TEST_P(InterruptControllerContract,
             OfTwoSourcesWithTheSamePriorityTheLowerNumberIsClaimedFirst) {
  std::uint32_t first = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Enable(bus, 5, /*priority=*/1);
    this->Enable(bus, 3, /*priority=*/1);
    this->Raise(bus, 5);
    this->Raise(bus, 3);
    first = this->Read(bus, this->kClaimComplete);
  });

  EXPECT_EQ(first, 3U);
}

TYPED_TEST_P(InterruptControllerContract,
             TheLastSourcesPriorityIsTheOneItWasGiven) {
  std::uint32_t first = 0;

  this->OnTheBus([&](BusDriver& bus) {
    this->Enable(bus, 3, /*priority=*/2);
    this->Enable(bus, this->kLastSource, /*priority=*/1);
    this->Raise(bus, 3);
    this->Raise(bus, this->kLastSource);
    first = this->Read(bus, this->kClaimComplete);
  });

  EXPECT_EQ(first, 3U);
}

TYPED_TEST_P(InterruptControllerContract, AClaimWithNothingPendingReadsZero) {
  std::uint32_t claimed = 99;

  this->OnTheBus([&](BusDriver& bus) {
    this->Enable(bus, 3, /*priority=*/1);
    claimed = this->Read(bus, this->kClaimComplete);
  });

  EXPECT_EQ(claimed, 0U);
}

TYPED_TEST_P(InterruptControllerContract,
             AClaimedSourceDoesNotInterruptAgainUntilItIsCompleted) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Enable(bus, 3, /*priority=*/1);
    this->Raise(bus, 3);
    this->Read(bus, this->kClaimComplete);
    // The device interrupts again while its handler is still running.
    this->Lower(bus, 3);
    this->Raise(bus, 3);
  });

  EXPECT_FALSE(this->interrupt_.read());
}

TYPED_TEST_P(InterruptControllerContract,
             CompletingASourceWhoseLineIsStillHighInterruptsAgain) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Enable(bus, 3, /*priority=*/1);
    this->Raise(bus, 3);
    const std::uint32_t claimed = this->Read(bus, this->kClaimComplete);
    // The handler finishes without the device having gone quiet.
    this->Write(bus, this->kClaimComplete, claimed);
  });

  EXPECT_TRUE(this->interrupt_.read());
}

TYPED_TEST_P(InterruptControllerContract,
             CompletingASourceWhoseLineHasDroppedDoesNotInterruptAgain) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Enable(bus, 3, /*priority=*/1);
    this->Raise(bus, 3);
    const std::uint32_t claimed = this->Read(bus, this->kClaimComplete);
    this->Lower(bus, 3);
    this->Write(bus, this->kClaimComplete, claimed);
  });

  EXPECT_FALSE(this->interrupt_.read());
}

TYPED_TEST_P(InterruptControllerContract,
             ASourceThatRisesInTheSameDeltaCycleAsAnEnableWriteInterrupts) {
  this->OnTheBus([&](BusDriver& bus) {
    this->Write(bus, this->Priority(3), 1);
    this->RaiseWithoutSettling(bus, 3);
    this->Write(bus, this->kEnable, std::uint32_t{1} << 3);
  });

  EXPECT_TRUE(this->interrupt_.read());
}

TYPED_TEST_P(InterruptControllerContract,
             ARegisterForSourcesItDoesNotHaveReadsZeroAndIgnoresWrites) {
  // The enable bits for sources 32 to 63, which a driver may clear without
  // asking how many sources there are.
  const std::uint64_t reserved = this->kEnable + 4;
  tlm::tlm_response_status write_response = tlm::TLM_INCOMPLETE_RESPONSE;
  std::array<std::uint8_t, 4> read{0xFF, 0xFF, 0xFF, 0xFF};
  tlm::tlm_response_status read_response = tlm::TLM_INCOMPLETE_RESPONSE;

  this->OnTheBus([&](BusDriver& bus) {
    const std::array<std::uint8_t, 4> ones{0xFF, 0xFF, 0xFF, 0xFF};
    write_response = bus.Write(reserved, ones);
    read_response = bus.Read(reserved, read);
  });

  EXPECT_EQ(write_response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(read_response, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(read, (std::array<std::uint8_t, 4>{0, 0, 0, 0}));
}

REGISTER_TYPED_TEST_SUITE_P(
    InterruptControllerContract,
    AnEnabledSourceWithAPriorityInterruptsWhenItsLineRises,
    ASourceThatIsNotEnabledDoesNot,
    ASourceWhosePriorityIsNotAboveTheThresholdDoesNot,
    ASourceEnabledWhileItsLineIsAlreadyHighInterrupts,
    AClaimSaysWhichSourceItWasAndEndsTheInterrupt,
    OfTwoSourcesTheOneWithTheHigherPriorityIsClaimedFirst,
    OfTwoSourcesWithTheSamePriorityTheLowerNumberIsClaimedFirst,
    TheLastSourcesPriorityIsTheOneItWasGiven, AClaimWithNothingPendingReadsZero,
    AClaimedSourceDoesNotInterruptAgainUntilItIsCompleted,
    CompletingASourceWhoseLineIsStillHighInterruptsAgain,
    CompletingASourceWhoseLineHasDroppedDoesNotInterruptAgain,
    ASourceThatRisesInTheSameDeltaCycleAsAnEnableWriteInterrupts,
    ARegisterForSourcesItDoesNotHaveReadsZeroAndIgnoresWrites);

#endif  // TESTS_CPP_CONTRACTS_INTERRUPT_CONTROLLER_CONTRACT_H_
