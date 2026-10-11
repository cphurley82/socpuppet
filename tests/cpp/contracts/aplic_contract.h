#ifndef TESTS_CPP_CONTRACTS_APLIC_CONTRACT_H_
#define TESTS_CPP_CONTRACTS_APLIC_CONTRACT_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/platform/slots.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/recording_target.h"

// What every RISC-V APLIC (advanced platform-level interrupt controller)
// must do when it delivers by message, whatever is behind it: the lines of
// devices that only have a wire come in, and for each interrupt a write
// goes out to the page of a hart's IMSIC. This is the part that Zephyr's
// driver and socpuppet's glue around it rely on, for one hart and
// level-sensitive sources.
//
// To hold an implementation to this contract:
//   INSTANTIATE_TYPED_TEST_SUITE_P(Mine, AplicContract,
//                                  ::testing::Types<MyAplic>);
// MyAplic must fit the APLIC slot (see socpuppet/platform/slots.h) and
// have at least 31 sources.
template <socpuppet::AplicSlot AplicType>
class AplicContract : public ::testing::Test {
 protected:
  // The APLIC's registers, 32 bits each. Sources are numbered from 1.
  static constexpr std::uint64_t kDomainConfiguration = 0x0000;
  static constexpr std::uint64_t SourceConfiguration(unsigned source) {
    return std::uint64_t{4} * source;
  }
  // Where messages for machine mode go: the number of the page of hart 0's
  // IMSIC, which is its address with the low twelve bits dropped. The
  // second register has the address's high bits and how the pages of
  // further harts are laid out.
  static constexpr std::uint64_t kMessageAddress = 0x1BC0;
  static constexpr std::uint64_t kMessageAddressHigh = 0x1BC4;
  // The same for supervisor mode.
  static constexpr std::uint64_t kSupervisorMessageAddress = 0x1BC8;
  static constexpr std::uint64_t kSupervisorMessageAddressHigh = 0x1BCC;
  // Written with a source's number, to have the APLIC look at its line
  // again: if the line is asking, the source is pending. (The
  // specification's setipnum_le.)
  static constexpr std::uint64_t kSetPendingByNumber = 0x2000;
  // Written with a source's number, to let it interrupt and to stop it.
  static constexpr std::uint64_t kEnableByNumber = 0x1EDC;
  static constexpr std::uint64_t kDisableByNumber = 0x1FDC;
  // Where a source's interrupt goes: with messages, the hart in the top
  // fourteen bits and the identity to send in the low eleven.
  static constexpr std::uint64_t Target(unsigned source) {
    return 0x3000 + (std::uint64_t{4} * source);
  }

  // Domain configuration: the domain's interrupts are on, and it delivers
  // by message.
  static constexpr std::uint32_t kInterruptsOn = 1U << 8;
  static constexpr std::uint32_t kDeliversByMessage = 1U << 2;
  // Source configuration: the line is not listened to, and it asks while it
  // is high.
  static constexpr std::uint32_t kInactive = 0;
  static constexpr std::uint32_t kLevelHigh = 6;
  // And it asks while it is low.
  static constexpr std::uint32_t kLevelLow = 7;
  // Target: a bit the specification keeps for later, which Zephyr's
  // driver sets.
  static constexpr std::uint32_t kReservedTargetBit = 1U << 11;

  // Where the tests have messages sent, and the identities they give the
  // two sources they use.
  static constexpr std::uint64_t kHartsPage = 0x2400'0000;
  static constexpr unsigned kSource = 16;
  static constexpr std::uint32_t kIdentity = 33;
  static constexpr unsigned kLastSource = 31;
  static constexpr std::uint32_t kLastIdentity = 40;

  AplicContract() {
    for (unsigned source : {kSource, kLastSource}) {
      // Only the lines a test drives are connected.
      aplic_.sources[source - 1].bind(lines_[source]);
    }
    aplic_.msi.bind(harts_page_.socket);
  }

  // Runs `body` in a simulation thread wired to the APLIC, to completion,
  // and then lets what it set in motion settle.
  void OnTheBus(const std::function<void(BusDriver&)>& body) {
    BusDriver driver{"driver", [&](BusDriver& bus) {
                       body(bus);
                       Settle(bus);
                     }};
    driver.socket.bind(aplic_.socket);
    sc_core::sc_start();
  }

  // Lets a change to a line, and what follows from it, happen.
  static void Settle(BusDriver& bus) {
    bus.WaitFor(sc_core::sc_time{1, sc_core::SC_NS});
  }

  // What firmware does once: says where messages go and switches the
  // domain's interrupts on. It does not ask for delivery by message, as
  // Zephyr's driver does not, so every test that sends relies on the
  // domain delivering that way unasked.
  void SetUpTheDomain(BusDriver& bus) {
    bus.Write32(kMessageAddress, kHartsPage >> 12);
    bus.Write32(kDomainConfiguration, kInterruptsOn);
  }

  // What firmware does for each source it wants to hear of, apart from
  // enabling it: has its line listened to, and says which identity to send.
  void Route(BusDriver& bus, unsigned source, std::uint32_t identity) {
    bus.Write32(SourceConfiguration(source), kLevelHigh);
    bus.Write32(Target(source), identity);
  }
  void Enable(BusDriver& bus, unsigned source) {
    bus.Write32(kEnableByNumber, source);
  }

  void Raise(BusDriver& bus, unsigned source) {
    lines_[source].write(true);
    Settle(bus);
  }
  void Lower(BusDriver& bus, unsigned source) {
    lines_[source].write(false);
    Settle(bus);
  }

  // The identities sent so far, in order. A message is a 32-bit write of
  // an identity to the first word of the hart's page, and anything else
  // that went out fails the test.
  std::vector<std::uint32_t> Sent() const {
    std::vector<std::uint32_t> identities;
    for (const RecordedAccess& message : messages_) {
      EXPECT_EQ(message.address, kHartsPage);
      EXPECT_EQ(message.written.size(), 4U);
      if (message.written.size() != 4) continue;
      identities.push_back(
          socpuppet::LoadLittleEndian<std::uint32_t>(message.written));
    }
    return identities;
  }

  // How long whatever is between an APLIC and the hart takes over each
  // message here: a bus may take time, and a link to another die does.
  static sc_core::sc_time TimeAMessageTakes() {
    return sc_core::sc_time{5, sc_core::SC_NS};
  }

  AplicType aplic_{"aplic"};
  // The lines of the sources, by source number. Entry 0 is unused.
  sc_core::sc_vector<sc_core::sc_signal<bool>> lines_{"line", kLastSource + 1};
  std::vector<RecordedAccess> messages_;
  RecordingTarget harts_page_{"harts_page", messages_, TimeAMessageTakes()};
};

TYPED_TEST_SUITE_P(AplicContract);

TYPED_TEST_P(AplicContract,
             AnEnabledSourceWhoseLineRisesSendsItsIdentityToTheHartsPage) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
  });

  ASSERT_EQ(this->messages_.size(), 1U);
  EXPECT_EQ(this->messages_[0].address, this->kHartsPage);
  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

TYPED_TEST_P(AplicContract, ALineThatFallsAndRisesAgainSendsAgain) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
    this->Lower(bus, this->kSource);
    this->Raise(bus, this->kSource);
  });

  EXPECT_EQ(this->Sent(),
            (std::vector<std::uint32_t>{this->kIdentity, this->kIdentity}));
}

// A handler may return with its device still asking: a UART with a byte
// to send, say, whose handler only saw to the byte that came in. The line
// never fell, so nothing rises. Firmware has the source looked at again
// by writing its number here, which is what Linux does after each handler.
TYPED_TEST_P(AplicContract,
             AskedToLookAgainAtASourceWhoseLineIsStillHighItSendsAgain) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
    bus.Write32(this->kSetPendingByNumber, this->kSource);
  });

  EXPECT_EQ(this->Sent(),
            (std::vector<std::uint32_t>{this->kIdentity, this->kIdentity}));
}

TYPED_TEST_P(AplicContract,
             AskedToLookAgainAtASourceWhoseLineHasFallenItSendsNothing) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
    this->Lower(bus, this->kSource);
    bus.Write32(this->kSetPendingByNumber, this->kSource);
  });

  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

TYPED_TEST_P(AplicContract,
             ASourceThatIsNotEnabledSendsNothingUntilItIsEnabled) {
  std::vector<std::uint32_t> before;

  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Raise(bus, this->kSource);
    before = this->Sent();
    this->Enable(bus, this->kSource);
  });

  EXPECT_TRUE(before.empty());
  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

// A level that has gone is no interrupt, where a PLIC's edge would be.
TYPED_TEST_P(AplicContract,
             ASourceWhoseLineFellBeforeItWasEnabledSendsNothing) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Raise(bus, this->kSource);
    this->Lower(bus, this->kSource);
    this->Enable(bus, this->kSource);
  });

  EXPECT_TRUE(this->Sent().empty());
}

// A device may be asking before its driver has started: a byte typed at a
// console while the firmware was still booting.
TYPED_TEST_P(AplicContract,
             ASourceWhoseLineWasAlreadyHighWhenItWasSetUpSendsOnceEnabled) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Raise(bus, this->kSource);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
  });

  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

// Out of reset every source is inactive, and an inactive source cannot be
// enabled: the write is ignored, and is not remembered for later.
TYPED_TEST_P(AplicContract, ASourceEnabledWhileInactiveIsNotEnabled) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Enable(bus, this->kSource);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Raise(bus, this->kSource);
  });

  EXPECT_TRUE(this->Sent().empty());
}

// This is a driver's irq_disable and irq_enable.
TYPED_TEST_P(AplicContract, ASourceDisabledAndEnabledAgainSends) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    bus.Write32(this->kDisableByNumber, this->kSource);
    this->Raise(bus, this->kSource);
    this->Enable(bus, this->kSource);
  });

  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

// A driver's irq_enable sets the source up afresh each time it is called,
// and the line may be asking at that moment. A level that was already
// there, and already sent, is not a new interrupt.
TYPED_TEST_P(AplicContract,
             GivingASourceTheModeItHasWhileItsLineIsHighSendsNothingMore) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
    bus.Write32(this->SourceConfiguration(this->kSource), this->kLevelHigh);
  });

  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

TYPED_TEST_P(AplicContract, ASourceDisabledByNumberSendsNothing) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    bus.Write32(this->kDisableByNumber, this->kSource);
    this->Raise(bus, this->kSource);
  });

  EXPECT_TRUE(this->Sent().empty());
}

TYPED_TEST_P(AplicContract,
             WithTheDomainsInterruptsOffNothingIsSentUntilTheyAreOn) {
  std::vector<std::uint32_t> before;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kMessageAddress, this->kHartsPage >> 12);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
    before = this->Sent();
    bus.Write32(this->kDomainConfiguration, this->kInterruptsOn);
  });

  EXPECT_TRUE(before.empty());
  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

TYPED_TEST_P(AplicContract,
             WithTheDomainsInterruptsSwitchedOffAgainNothingIsSent) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    bus.Write32(this->kDomainConfiguration, 0);
    this->Raise(bus, this->kSource);
  });

  EXPECT_TRUE(this->Sent().empty());
}

// The identity is firmware's to choose, and need not be the source's
// number. The last source is as good as any other.
TYPED_TEST_P(AplicContract, EachSourceSendsTheIdentityItWasGiven) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Route(bus, this->kLastSource, this->kLastIdentity);
    this->Enable(bus, this->kSource);
    this->Enable(bus, this->kLastSource);
    this->Raise(bus, this->kLastSource);
    this->Raise(bus, this->kSource);
  });

  EXPECT_EQ(this->Sent(),
            (std::vector<std::uint32_t>{this->kLastIdentity, this->kIdentity}));
}

// Zephyr's driver sets this bit in every target it writes.
TYPED_TEST_P(AplicContract, ABitTheSpecificationKeepsInATargetIsNotSent) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    bus.Write32(this->SourceConfiguration(this->kSource), this->kLevelHigh);
    bus.Write32(this->Target(this->kSource),
                this->kIdentity | this->kReservedTargetBit);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
  });

  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

// Each hart's IMSIC has a page of its own. Firmware says how many bits of
// a hart's number tell the pages apart, and here it is one, so that hart 1
// has the page after hart 0's.
TYPED_TEST_P(AplicContract, AnInterruptForAnotherHartGoesToThatHartsPage) {
  constexpr std::uint32_t kOneBitOfHartNumber = 1U << 12;
  constexpr std::uint32_t kHartOne = 1U << 18;

  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    bus.Write32(this->kMessageAddressHigh, kOneBitOfHartNumber);
    bus.Write32(this->SourceConfiguration(this->kSource), this->kLevelHigh);
    bus.Write32(this->Target(this->kSource), kHartOne | this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
  });

  ASSERT_EQ(this->messages_.size(), 1U);
  EXPECT_EQ(this->messages_[0].address, this->kHartsPage + 0x1000);
}

// Zephyr's driver never asks for delivery by message. It reads this
// register, sets the bit that switches interrupts on and writes it back.
TYPED_TEST_P(AplicContract, OutOfResetTheDomainDeliversByMessage) {
  std::uint32_t out_of_reset = 0;

  this->OnTheBus([&](BusDriver& bus) {
    out_of_reset = bus.Read32(this->kDomainConfiguration);
  });

  EXPECT_EQ(out_of_reset & this->kDeliversByMessage, this->kDeliversByMessage);
}

// An APLIC with one way to deliver has that bit fixed. Firmware that
// writes the register whole, and leaves the bit out, changes nothing.
TYPED_TEST_P(AplicContract, TheDomainCannotBeToldNotToDeliverByMessage) {
  std::uint32_t with_interrupts_on = 0;
  std::uint32_t with_them_off = 0;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->kDomainConfiguration, this->kInterruptsOn);
    with_interrupts_on = bus.Read32(this->kDomainConfiguration);
    bus.Write32(this->kDomainConfiguration, 0);
    with_them_off = bus.Read32(this->kDomainConfiguration);
  });

  EXPECT_EQ(
      with_interrupts_on & (this->kDeliversByMessage | this->kInterruptsOn),
      this->kDeliversByMessage | this->kInterruptsOn);
  EXPECT_EQ(with_them_off & (this->kDeliversByMessage | this->kInterruptsOn),
            this->kDeliversByMessage);
}

// Zephyr's driver writes where messages go only if it reads zero in both
// registers, taking anything else for an address the hardware was built
// with.
TYPED_TEST_P(AplicContract,
             WhereMessagesGoReadsAsZeroUntilItIsWrittenAndThenAsWritten) {
  std::uint32_t out_of_reset = 1;
  std::uint32_t high_out_of_reset = 1;
  std::uint32_t written = 0;

  this->OnTheBus([&](BusDriver& bus) {
    out_of_reset = bus.Read32(this->kMessageAddress);
    high_out_of_reset = bus.Read32(this->kMessageAddressHigh);
    bus.Write32(this->kMessageAddress, this->kHartsPage >> 12);
    written = bus.Read32(this->kMessageAddress);
  });

  EXPECT_EQ(out_of_reset, 0U);
  EXPECT_EQ(high_out_of_reset, 0U);
  EXPECT_EQ(written, this->kHartsPage >> 12);
}

// What Zephyr's driver writes for one hart: no bits of a hart's number in
// either part, and a place for the high part all the same.
TYPED_TEST_P(AplicContract,
             WithTheLayoutZephyrGivesHartZerosPageIsTheOneGiven) {
  constexpr std::uint32_t kHighPartAt24AndNoBits = 24U << 24;

  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    bus.Write32(this->kMessageAddressHigh, kHighPartAt24AndNoBits);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
  });

  ASSERT_EQ(this->messages_.size(), 1U);
  EXPECT_EQ(this->messages_[0].address, this->kHartsPage);
}

// A domain for machine mode with none for supervisor mode under it has
// nowhere to keep this, and firmware may write it all the same, as
// Zephyr's driver does.
TYPED_TEST_P(AplicContract,
             WhereTheSupervisorsMessagesGoTakesAWriteAndReadsAsZero) {
  tlm::tlm_response_status low = tlm::TLM_INCOMPLETE_RESPONSE;
  tlm::tlm_response_status high = tlm::TLM_INCOMPLETE_RESPONSE;
  std::uint32_t read_back = 1;

  this->OnTheBus([&](BusDriver& bus) {
    low = bus.Write32(this->kSupervisorMessageAddress, this->kHartsPage >> 12);
    high = bus.Write32(this->kSupervisorMessageAddressHigh, 0);
    read_back = bus.Read32(this->kSupervisorMessageAddress);
  });

  EXPECT_EQ(low, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(high, tlm::TLM_OK_RESPONSE);
  EXPECT_EQ(read_back, 0U);
}

// Zephyr's driver sets a source's mode by reading the register and writing
// it back with the mode changed.
TYPED_TEST_P(AplicContract, ASourcesModeReadsBackWhatWasWritten) {
  std::uint32_t mode = 0;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->SourceConfiguration(this->kSource), this->kLevelHigh);
    mode = bus.Read32(this->SourceConfiguration(this->kSource));
  });

  EXPECT_EQ(mode, this->kLevelHigh);
}

// A register write may itself send, and whoever wrote it may be the far
// end of the very road the message takes. So the write returns first, and
// the message follows from a process of the APLIC's own.
TYPED_TEST_P(AplicContract, AMessageARegisterWriteCausesIsSentAfterTheWrite) {
  std::size_t as_the_write_returned = 1;

  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Raise(bus, this->kSource);
    this->Enable(bus, this->kSource);
    as_the_write_returned = this->messages_.size();
  });

  EXPECT_EQ(as_the_write_returned, 0U);
  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

// With messages a target has the hart and the identity and nothing else.
// The bits between them are for a hypervisor's guests, which this has
// none of, or are kept by the specification, and all read as zero.
TYPED_TEST_P(AplicContract, ATargetReadsBackTheHartAndTheIdentityOnly) {
  constexpr std::uint32_t kHartOne = 1U << 18;
  constexpr std::uint32_t kAnIdentity = 0x100;
  constexpr std::uint32_t kEverythingBetween = 0x0003'F800;
  std::uint32_t target = 0;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write32(this->SourceConfiguration(this->kSource), this->kLevelHigh);
    bus.Write32(this->Target(this->kSource),
                kHartOne | kEverythingBetween | kAnIdentity);
    target = bus.Read32(this->Target(this->kSource));
  });

  EXPECT_EQ(target, kHartOne | kAnIdentity);
}

// The whole of how a hart's page is found. A hart's number is in two
// parts: here the low part is two bits, put into the page number one bit
// up, and the high part is the one bit above them, put four bits above
// where the page number's bit 12 is. Hart 6 is binary 110: a high part of
// 1 and a low part of 2. The address has high bits of its own too.
TYPED_TEST_P(AplicContract, AHartsPageIsWhereTheLayoutFirmwareGavePutsIt) {
  constexpr std::uint32_t kAddressBit44 = 1U;
  constexpr std::uint32_t kLowPartTwoBits = 2U << 12;
  constexpr std::uint32_t kHighPartOneBit = 1U << 16;
  constexpr std::uint32_t kLowPartOneBitUp = 1U << 20;
  constexpr std::uint32_t kHighPartFourBitsUp = 4U << 24;
  constexpr std::uint32_t kHartSix = 6U << 18;

  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    bus.Write32(this->kMessageAddressHigh,
                kAddressBit44 | kLowPartTwoBits | kHighPartOneBit |
                    kLowPartOneBitUp | kHighPartFourBitsUp);
    bus.Write32(this->SourceConfiguration(this->kSource), this->kLevelHigh);
    bus.Write32(this->Target(this->kSource), kHartSix | this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
  });

  ASSERT_EQ(this->messages_.size(), 1U);
  EXPECT_EQ(
      this->messages_[0].address,
      (std::uint64_t{1} << 44) + this->kHartsPage + (1U << 28) + (1U << 14));
}

// Whatever is between the APLIC and the hart takes its time over a
// message, and the next one waits for it.
TYPED_TEST_P(AplicContract, TheNextMessageWaitsForTheOneBeforeItToArrive) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Route(bus, this->kLastSource, this->kLastIdentity);
    this->lines_[this->kSource].write(true);
    this->lines_[this->kLastSource].write(true);
    this->Settle(bus);
    this->Enable(bus, this->kSource);
    this->Enable(bus, this->kLastSource);
    bus.WaitFor(sc_core::sc_time{1, sc_core::SC_US});
  });

  ASSERT_EQ(this->messages_.size(), 2U);
  EXPECT_GE(this->messages_[1].kernel_time - this->messages_[0].kernel_time,
            this->TimeAMessageTakes());
}

TYPED_TEST_P(AplicContract,
             AskedToLookAtASourceThatIsInactiveItDoesNotAndSendsNothingLater) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    bus.Write32(this->kSetPendingByNumber, this->kSource);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
  });

  EXPECT_TRUE(this->Sent().empty());
}

// Source 0 means "none", and there are fewer sources than there are
// numbers to write. A source that does exist is asking meanwhile, so that
// a write taken for it would show.
TYPED_TEST_P(AplicContract,
             AskedToLookAtASourceThatDoesNotExistItSendsNothing) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Raise(bus, this->kSource);
    bus.Write32(this->kSetPendingByNumber, 0);
    bus.Write32(this->kSetPendingByNumber, 0xFFFF'FFFF);
  });

  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

// Some devices ask by pulling their line low, and a source can be set up
// for that. A line that nobody has driven is low.
TYPED_TEST_P(
    AplicContract,
    ASourceSetUpToAskWhileItsLineIsLowSendsWhileItIsLowAndNotWhileHigh) {
  std::vector<std::uint32_t> while_low;

  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    bus.Write32(this->SourceConfiguration(this->kSource), this->kLevelLow);
    bus.Write32(this->Target(this->kSource), this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Settle(bus);
    while_low = this->Sent();
    this->Raise(bus, this->kSource);
    bus.Write32(this->kSetPendingByNumber, this->kSource);
  });

  EXPECT_EQ(while_low, std::vector<std::uint32_t>{this->kIdentity});
  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

TYPED_TEST_P(AplicContract,
             ASourceSetUpToAskWhileItsLineIsLowSendsWhenItsLineFalls) {
  std::vector<std::uint32_t> while_high;

  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Raise(bus, this->kSource);
    bus.Write32(this->SourceConfiguration(this->kSource), this->kLevelLow);
    bus.Write32(this->Target(this->kSource), this->kIdentity);
    this->Enable(bus, this->kSource);
    this->Settle(bus);
    while_high = this->Sent();
    this->Lower(bus, this->kSource);
  });

  EXPECT_TRUE(while_high.empty());
  EXPECT_EQ(this->Sent(), std::vector<std::uint32_t>{this->kIdentity});
}

// What a source was asking before it was made inactive is forgotten, and
// so is that it was enabled.
TYPED_TEST_P(AplicContract,
             ASourceMadeInactiveForgetsThatItWasAskingAndEnabled) {
  this->OnTheBus([&](BusDriver& bus) {
    this->SetUpTheDomain(bus);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Raise(bus, this->kSource);
    bus.Write32(this->SourceConfiguration(this->kSource), this->kInactive);
    this->Lower(bus, this->kSource);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Enable(bus, this->kSource);
    bus.Write32(this->SourceConfiguration(this->kSource), this->kInactive);
    this->Route(bus, this->kSource, this->kIdentity);
    this->Raise(bus, this->kSource);
  });

  EXPECT_TRUE(this->Sent().empty());
}

// The bit is in the register's first byte, and a byte can be written alone.
TYPED_TEST_P(AplicContract,
             TheDomainCannotBeToldNotToDeliverByMessageAByteAtATime) {
  std::uint32_t domain = 0;

  this->OnTheBus([&](BusDriver& bus) {
    bus.Write(this->kDomainConfiguration, std::array<std::uint8_t, 1>{0});
    domain = bus.Read32(this->kDomainConfiguration);
  });

  EXPECT_EQ(domain & this->kDeliversByMessage, this->kDeliversByMessage);
}

REGISTER_TYPED_TEST_SUITE_P(
    AplicContract, AnEnabledSourceWhoseLineRisesSendsItsIdentityToTheHartsPage,
    ALineThatFallsAndRisesAgainSendsAgain,
    AskedToLookAgainAtASourceWhoseLineIsStillHighItSendsAgain,
    AskedToLookAgainAtASourceWhoseLineHasFallenItSendsNothing,
    ASourceThatIsNotEnabledSendsNothingUntilItIsEnabled,
    ASourceWhoseLineFellBeforeItWasEnabledSendsNothing,
    ASourceWhoseLineWasAlreadyHighWhenItWasSetUpSendsOnceEnabled,
    ASourceEnabledWhileInactiveIsNotEnabled,
    ASourceDisabledAndEnabledAgainSends,
    GivingASourceTheModeItHasWhileItsLineIsHighSendsNothingMore,
    ASourceDisabledByNumberSendsNothing,
    WithTheDomainsInterruptsOffNothingIsSentUntilTheyAreOn,
    WithTheDomainsInterruptsSwitchedOffAgainNothingIsSent,
    EachSourceSendsTheIdentityItWasGiven,
    ABitTheSpecificationKeepsInATargetIsNotSent,
    AnInterruptForAnotherHartGoesToThatHartsPage,
    OutOfResetTheDomainDeliversByMessage,
    TheDomainCannotBeToldNotToDeliverByMessage,
    WhereMessagesGoReadsAsZeroUntilItIsWrittenAndThenAsWritten,
    WithTheLayoutZephyrGivesHartZerosPageIsTheOneGiven,
    WhereTheSupervisorsMessagesGoTakesAWriteAndReadsAsZero,
    ASourcesModeReadsBackWhatWasWritten,
    AMessageARegisterWriteCausesIsSentAfterTheWrite,
    ATargetReadsBackTheHartAndTheIdentityOnly,
    AHartsPageIsWhereTheLayoutFirmwareGavePutsIt,
    TheNextMessageWaitsForTheOneBeforeItToArrive,
    AskedToLookAtASourceThatIsInactiveItDoesNotAndSendsNothingLater,
    AskedToLookAtASourceThatDoesNotExistItSendsNothing,
    ASourceSetUpToAskWhileItsLineIsLowSendsWhileItIsLowAndNotWhileHigh,
    ASourceSetUpToAskWhileItsLineIsLowSendsWhenItsLineFalls,
    ASourceMadeInactiveForgetsThatItWasAskingAndEnabled,
    TheDomainCannotBeToldNotToDeliverByMessageAByteAtATime);

#endif  // TESTS_CPP_CONTRACTS_APLIC_CONTRACT_H_
