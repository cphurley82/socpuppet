#include "socpuppet/core/ucie_link_registers.h"

#include <array>
#include <cstdint>
#include <ios>
#include <optional>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/ucie_link_state.h"
#include "socpuppet/core/ucie_sideband.h"

namespace socpuppet {
namespace {

// The offsets in the block. The first three are where PCIe puts the
// headers of a vendor-specific capability, and the rest are UCIe's Link
// DVSEC and the block of our own that its register locator points at.
constexpr std::uint64_t kExtendedCapabilityHeader = 0x00;
constexpr std::uint64_t kDvsecHeader1 = 0x04;
constexpr std::uint64_t kLinkControl = 0x10;
constexpr std::uint64_t kLinkStatus = 0x14;
constexpr std::uint64_t kNotification = 0x18;
constexpr std::uint64_t kRegisterLocator = 0x1C;
constexpr std::uint64_t kDieReset = 0x24;
constexpr std::uint64_t kFaultInjection = 0x28;
constexpr std::uint64_t kMailboxOpcode = 0x40;
constexpr std::uint64_t kMailboxAddress = 0x48;
constexpr std::uint64_t kMailboxData = 0x50;
constexpr std::uint64_t kMailboxTrigger = 0x58;
constexpr std::uint64_t kMailboxStatus = 0x5C;

// An address the mailbox is pointed at, which stands for nothing: the
// mailbox does not look at what is there.
constexpr std::uint32_t kSomewhereOnTheOtherDie = 0x5BA17;

// The bits the tests name.
constexpr std::uint32_t kStartTraining = 1U << 0;
constexpr std::uint32_t kRetrainLink = 1U << 1;
constexpr std::uint32_t kLinkUp = 1U << 0;
constexpr std::uint32_t kLinkTraining = 1U << 1;
constexpr std::uint32_t kLinkStatusChanged = 1U << 2;
constexpr std::uint32_t kStatusChangedInterrupt = 1U << 0;
constexpr std::uint32_t kMailboxBusy = 1U << 8;

std::uint32_t Read32(const UcieLinkRegisters& registers, std::uint64_t offset) {
  std::array<std::uint8_t, 4> bytes{};
  registers.ReadRegister(offset, bytes);
  return LoadLittleEndian<std::uint32_t>(bytes);
}

bool Write32(UcieLinkRegisters& registers, std::uint64_t offset,
             std::uint32_t value) {
  return registers.WriteRegister(offset, LittleEndianBytes(value));
}

TEST(WhenTheExtendedCapabilityHeaderIsRead, ItNamesAVendorSpecificOne) {
  const UcieLinkRegisters registers;

  // 0x0023 is PCIe's identifier for a designated vendor-specific
  // extended capability, which is how UCIe's link registers are found.
  EXPECT_EQ(Read32(registers, kExtendedCapabilityHeader) & 0xFFFFU, 0x0023U);
}

TEST(WhenTheDvsecHeaderIsRead, ItNamesUcieAsTheVendor) {
  const UcieLinkRegisters registers;

  EXPECT_EQ(Read32(registers, kDvsecHeader1) & 0xFFFFU, 0xD2DEU);
}

TEST(WhenTheRegisterLocatorIsRead, ItSaysWhereTheLinksOwnBlockIs) {
  UcieLinkRegisters registers;
  registers.LinkIs(LinkTrainingState::kSbinit);

  // The first register of the block it points at is where the link says
  // which training state it is in.
  const std::uint64_t block = Read32(registers, kRegisterLocator) >> 8;
  EXPECT_EQ(Read32(registers, block),
            static_cast<std::uint32_t>(LinkTrainingState::kSbinit));
}

TEST(WhenFirmwareAsksForTrainingToStart, TheLinkIsToldToTrain) {
  UcieLinkRegisters registers;

  Write32(registers, kLinkControl, kStartTraining);

  EXPECT_TRUE(registers.TakeCommands().start_training);
}

TEST(WhenFirmwareAsksForARetrain, TheLinkIsToldToTrainAgain) {
  UcieLinkRegisters registers;

  Write32(registers, kLinkControl, kRetrainLink);

  EXPECT_TRUE(registers.TakeCommands().retrain);
}

TEST(WhenTheControlBitsAreReadBack, TheyHaveClearedThemselves) {
  UcieLinkRegisters registers;
  Write32(registers, kLinkControl, kStartTraining | kRetrainLink);

  EXPECT_EQ(Read32(registers, kLinkControl) & (kStartTraining | kRetrainLink),
            0U);
}

TEST(WhenTheLinkIsTraining, TheStatusSaysSoAndNotThatItIsUp) {
  UcieLinkRegisters registers;

  registers.LinkIs(LinkTrainingState::kSbinit);

  EXPECT_EQ(Read32(registers, kLinkStatus) & (kLinkUp | kLinkTraining),
            kLinkTraining);
}

TEST(WhenTheLinkComesUp, TheStatusSaysItIsUpAndThatItChanged) {
  UcieLinkRegisters registers;

  registers.LinkIs(LinkTrainingState::kActive);

  EXPECT_EQ(Read32(registers, kLinkStatus) & (kLinkUp | kLinkStatusChanged),
            kLinkUp | kLinkStatusChanged);
}

TEST(WhenFirmwareWritesAOneToTheChangedBit, ItIsCleared) {
  UcieLinkRegisters registers;
  registers.LinkIs(LinkTrainingState::kActive);

  Write32(registers, kLinkStatus, kLinkStatusChanged);

  EXPECT_EQ(Read32(registers, kLinkStatus) & kLinkStatusChanged, 0U);
}

TEST(WhenTheLinkChangesAndTheInterruptIsEnabled, TheEndpointInterrupts) {
  UcieLinkRegisters registers;
  Write32(registers, kNotification, kStatusChangedInterrupt);

  registers.LinkIs(LinkTrainingState::kActive);

  EXPECT_TRUE(registers.Interrupting());
}

TEST(WhenTheLinkChangesAndTheInterruptIsNotEnabled, NothingInterrupts) {
  UcieLinkRegisters registers;

  registers.LinkIs(LinkTrainingState::kActive);

  EXPECT_FALSE(registers.Interrupting());
}

TEST(WhenAnEndpointIsPoweredOn, ItHoldsItsOwnDieInReset) {
  const UcieLinkRegisters registers;

  EXPECT_TRUE(registers.ResetAsserted());
}

TEST(WhenTheResetRegisterIsWrittenAZero, TheDieIsLetGo) {
  UcieLinkRegisters registers;

  Write32(registers, kDieReset, 0);

  EXPECT_FALSE(registers.ResetAsserted());
}

TEST(WhenFirmwareTriggersTheMailbox, ItAsksForThatRegisterOfTheOtherDie) {
  UcieLinkRegisters registers;
  Write32(registers, kMailboxOpcode,
          static_cast<std::uint32_t>(SidebandOpcode::kMemoryRead32b));
  Write32(registers, kMailboxAddress, kSomewhereOnTheOtherDie);

  Write32(registers, kMailboxTrigger, 1);

  const std::optional<MailboxRequest> request =
      registers.TakeCommands().mailbox;
  EXPECT_EQ(request, (MailboxRequest{.opcode = SidebandOpcode::kMemoryRead32b,
                                     .address = kSomewhereOnTheOtherDie}));
}

TEST(WhenAMailboxRequestIsTriggered, TheStatusSaysItIsWaitingForAnAnswer) {
  UcieLinkRegisters registers;

  Write32(registers, kMailboxTrigger, 1);

  EXPECT_EQ(Read32(registers, kMailboxStatus) & kMailboxBusy, kMailboxBusy);
}

TEST(WhenAMailboxRequestIsAnswered, TheStatusStopsSayingItIsWaiting) {
  UcieLinkRegisters registers;
  Write32(registers, kMailboxTrigger, 1);

  registers.MailboxAnswered(SidebandStatus::kSuccess, 0);

  EXPECT_EQ(Read32(registers, kMailboxStatus) & kMailboxBusy, 0U);
}

TEST(WhenAMailboxRequestIsAnswered, ItsDataAndStatusAreThereToRead) {
  UcieLinkRegisters registers;

  registers.MailboxAnswered(SidebandStatus::kSuccess, 0xC0FF'EE00);

  EXPECT_EQ(Read32(registers, kMailboxData), 0xC0FF'EE00U);
  EXPECT_EQ(Read32(registers, kMailboxStatus),
            static_cast<std::uint32_t>(SidebandStatus::kSuccess));
}

TEST(WhenFirmwareInjectsAFault, TheLinkIsToldToFault) {
  UcieLinkRegisters registers;

  Write32(registers, kFaultInjection, 1);

  EXPECT_TRUE(registers.TakeCommands().fault);
}

TEST(WhenAnAccessToTheBlockIsNot32BitsWide, ItIsRefused) {
  UcieLinkRegisters registers;
  std::array<std::uint8_t, 2> half{};

  EXPECT_FALSE(registers.ReadRegister(kLinkStatus, half));
}

TEST(WhenAnAccessStartsPastTheEndOfTheBlock, ItIsRefused) {
  UcieLinkRegisters registers;

  EXPECT_FALSE(Write32(registers, UcieLinkRegisters::kSize, 1));
}

TEST(WhenTheRegistersAreRead, TheyAskNothingOfTheLink) {
  UcieLinkRegisters registers;
  Read32(registers, kLinkControl);
  Read32(registers, kMailboxTrigger);
  Read32(registers, kFaultInjection);

  const UcieLinkRegisters::Commands commands = registers.TakeCommands();

  EXPECT_FALSE(commands.start_training || commands.retrain || commands.fault ||
               commands.mailbox.has_value());
}

}  // namespace
}  // namespace socpuppet
