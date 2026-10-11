#include "socpuppet/core/interrupt_file.h"

#include <cstdint>

#include <gtest/gtest.h>

namespace socpuppet {

namespace {

// A file with 63 identities whose delivery firmware has switched on.
InterruptFile Delivering() {
  InterruptFile file{/*identities=*/63};
  file.Write(InterruptFile::kEidelivery, 1);
  return file;
}

// The bit of an identity in a register of enables or of pending bits.
constexpr std::uint64_t Bit(unsigned identity) {
  return std::uint64_t{1} << identity;
}

}  // namespace

TEST(WhenAnInterruptFileIsNew, ItInterruptsNobody) {
  const InterruptFile file{/*identities=*/63};

  EXPECT_FALSE(file.Interrupting());
}

TEST(WhenAnIdentityFirmwareHasEnabledIsDelivered,
     TheFileInterruptsAndThatIdentityIsItsTop) {
  InterruptFile file = Delivering();
  file.Write(InterruptFile::kEie0, Bit(5));

  file.Deliver(5);

  EXPECT_TRUE(file.Interrupting());
  EXPECT_EQ(file.Top(), 5U);
}

TEST(WhenAnIdentityFirmwareHasNotEnabledIsDelivered,
     ItWaitsAndInterruptsOnceItIsEnabled) {
  InterruptFile file = Delivering();

  file.Deliver(5);
  const bool interrupted_before = file.Interrupting();
  file.Write(InterruptFile::kEie0, Bit(5));

  EXPECT_FALSE(interrupted_before);
  EXPECT_TRUE(file.Interrupting());
}

TEST(WhenDeliveryIsSwitchedOff, AnEnabledIdentityIsTheTopAndDoesNotInterrupt) {
  InterruptFile file = Delivering();
  file.Write(InterruptFile::kEidelivery, 0);
  file.Write(InterruptFile::kEie0, Bit(5));

  file.Deliver(5);

  EXPECT_EQ(file.Top(), 5U);
  EXPECT_FALSE(file.Interrupting());
}

// A lower identity has the higher priority.
TEST(WhenTwoEnabledIdentitiesArePending, TheLowerIsTheTop) {
  InterruptFile file = Delivering();
  file.Write(InterruptFile::kEie0, Bit(9) | Bit(5));

  file.Deliver(9);
  file.Deliver(5);

  EXPECT_EQ(file.Top(), 5U);
}

TEST(WhenTheTopIsClaimed, ItIsNoLongerPendingAndTheNextIsTheTop) {
  InterruptFile file = Delivering();
  file.Write(InterruptFile::kEie0, Bit(9) | Bit(5));
  file.Deliver(9);
  file.Deliver(5);

  const std::uint32_t claimed = file.Claim();

  EXPECT_EQ(claimed, 5U);
  EXPECT_EQ(file.Top(), 9U);
}

TEST(WhenAnIdentityIsDelivered, ItsBitIsSetInTheRegisterOfPendingOnes) {
  InterruptFile file{/*identities=*/63};

  file.Deliver(5);

  EXPECT_EQ(file.Read(InterruptFile::kEip0), Bit(5));
}

// Identity zero means "none", which is what a claim returns when nothing is
// pending.
TEST(WhenAMessageNamesIdentityZero, NothingBecomesPending) {
  InterruptFile file{/*identities=*/63};

  file.Deliver(0);

  EXPECT_EQ(file.Read(InterruptFile::kEip0), 0U);
}

TEST(WhenAMessageNamesAnIdentityPastTheFilesLast, NothingBecomesPending) {
  // A file with fewer identities than a register has bits, so that the
  // bit past its last is one that could be set.
  InterruptFile file{/*identities=*/15};

  file.Deliver(16);

  EXPECT_EQ(file.Read(InterruptFile::kEip0), 0U);
}

// A threshold of zero, which a file starts with, holds nothing back.
TEST(WhenFirmwareSetsAThreshold, OnlyAnIdentityBelowItCanBeTheTop) {
  InterruptFile file = Delivering();
  file.Write(InterruptFile::kEie0, Bit(9) | Bit(5));
  file.Write(InterruptFile::kEithreshold, 9);

  file.Deliver(9);
  const std::uint32_t top_with_the_one_at_the_threshold = file.Top();
  file.Deliver(5);

  EXPECT_EQ(top_with_the_one_at_the_threshold, 0U);
  EXPECT_EQ(file.Top(), 5U);
}

TEST(WhenFirmwareWritesWhichIdentitiesItWants,
     TheRegisterReadsBackWhatItWrote) {
  InterruptFile file{/*identities=*/63};

  file.Write(InterruptFile::kEie0, Bit(9) | Bit(5));

  EXPECT_EQ(file.Read(InterruptFile::kEie0), Bit(9) | Bit(5));
}

TEST(WhenFirmwareSwitchesDeliveryOnAndSetsAThreshold,
     BothRegistersReadBackWhatItWrote) {
  InterruptFile file{/*identities=*/63};

  file.Write(InterruptFile::kEidelivery, 1);
  file.Write(InterruptFile::kEithreshold, 9);

  EXPECT_EQ(file.Read(InterruptFile::kEidelivery), 1U);
  EXPECT_EQ(file.Read(InterruptFile::kEithreshold), 9U);
}

// Firmware can ask for an interrupt itself, with no message sent.
TEST(WhenFirmwareWritesTheRegisterOfPendingOnes,
     TheIdentitiesItSetArePendingAndTheOnesItClearedAreNot) {
  InterruptFile file = Delivering();
  file.Write(InterruptFile::kEie0, Bit(9) | Bit(5));
  file.Deliver(5);

  file.Write(InterruptFile::kEip0, Bit(9));

  EXPECT_EQ(file.Top(), 9U);
}

TEST(WhenFirmwareWritesABitForIdentityZeroOrForOneTheFileHasNot,
     TheBitReadsBackAsZero) {
  InterruptFile file{/*identities=*/15};

  file.Write(InterruptFile::kEie0, ~std::uint64_t{0});
  file.Write(InterruptFile::kEip0, ~std::uint64_t{0});

  // Identities 1 to 15 and no others.
  EXPECT_EQ(file.Read(InterruptFile::kEie0), 0xFFFEU);
  EXPECT_EQ(file.Read(InterruptFile::kEip0), 0xFFFEU);
}

// What is pending is a bit, not a count.
TEST(WhenTheSameIdentityIsDeliveredTwiceBeforeItIsClaimed, ItIsClaimedOnce) {
  InterruptFile file = Delivering();
  file.Write(InterruptFile::kEie0, Bit(5));
  file.Deliver(5);
  file.Deliver(5);

  const std::uint32_t first = file.Claim();
  const std::uint32_t second = file.Claim();

  EXPECT_EQ(first, 5U);
  EXPECT_EQ(second, 0U);
}

// With registers of 64 bits, which is all there is here, the specification
// numbers them in twos: 0x80, 0x82 and so on. The odd ones do not exist,
// and a hart that selects one takes an illegal-instruction trap.
TEST(WhenAnOddNumberedRegisterOfBitsIsReadOrWritten, TheFileSaysItHasNoSuch) {
  InterruptFile file{/*identities=*/63};

  EXPECT_FALSE(file.Read(InterruptFile::kEip0 + 1).has_value());
  EXPECT_FALSE(file.Write(InterruptFile::kEie0 + 1, 1));
}

// 0x71 and 0x73 to 0x7F, which the specification keeps for itself.
TEST(WhenARegisterTheSpecificationReservesIsWrittenAndRead, ItReadsAsZero) {
  InterruptFile file{/*identities=*/63};

  const bool there_is_such_a_register = file.Write(0x71, 0x5A);

  EXPECT_TRUE(there_is_such_a_register);
  EXPECT_EQ(file.Read(0x71), 0U);
  EXPECT_EQ(file.Read(0x7F), 0U);
}

TEST(WhenARegisterOfBitsPastTheFilesLastIdentityIsWrittenAndRead,
     ItReadsAsZero) {
  InterruptFile file{/*identities=*/63};

  const bool there_is_such_a_register =
      file.Write(InterruptFile::kEie0 + 2, ~std::uint64_t{0});

  EXPECT_TRUE(there_is_such_a_register);
  EXPECT_EQ(file.Read(InterruptFile::kEie0 + 2), 0U);
}

TEST(WhenAFileHasMoreIdentitiesThanOneRegisterHolds,
     TheNextSixtyFourAreInTheNextRegisterOfEachKind) {
  InterruptFile file{/*identities=*/100};

  // Identity 100 is bit 36 of the second register, and the file's last.
  file.Write(InterruptFile::kEie0 + 2, ~std::uint64_t{0});
  file.Deliver(100);

  EXPECT_EQ(file.Read(InterruptFile::kEie0 + 2), (Bit(37) - 1));
  EXPECT_EQ(file.Read(InterruptFile::kEip0 + 2), Bit(36));
  EXPECT_EQ(file.Read(InterruptFile::kEip0), 0U);
}

TEST(WhenIdentitiesInTwoRegistersArePending,
     TheLowestIsTheTopAndClaimingEachLeavesTheNext) {
  InterruptFile file{/*identities=*/127};
  file.Write(InterruptFile::kEidelivery, 1);
  file.Write(InterruptFile::kEie0, Bit(5));
  file.Write(InterruptFile::kEie0 + 2, Bit(100 - 64));
  file.Deliver(100);
  file.Deliver(5);

  const std::uint32_t first = file.Claim();
  const std::uint32_t second = file.Claim();

  EXPECT_EQ(first, 5U);
  EXPECT_EQ(second, 100U);
  EXPECT_FALSE(file.Interrupting());
}

// The other tests name the registers as the file does. This one names
// them as firmware does, by the numbers the AIA specification gives them.
TEST(WhenFirmwareSelectsRegistersByTheSpecificationsNumbers,
     TheFileAnswersAsThoseRegisters) {
  InterruptFile file{/*identities=*/63};
  file.Write(0x70, 1);       // eidelivery
  file.Write(0xC0, Bit(5));  // eie0
  file.Write(0x72, 5);       // eithreshold
  file.Deliver(5);

  EXPECT_EQ(file.Read(0x80), Bit(5));  // eip0
  EXPECT_EQ(file.Top(), 0U);           // held back by the threshold
  EXPECT_FALSE(file.Interrupting());
}

}  // namespace socpuppet
