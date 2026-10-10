#include "socpuppet/core/ucie_link_registers.h"

#include <array>
#include <cstdint>
#include <ios>
#include <optional>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/ucie_link_state.h"
#include "socpuppet/core/ucie_sideband.h"
#include "socpuppet/regs/ucie_link.h"

namespace socpuppet {
namespace {

// An address the mailbox is pointed at, which stands for nothing: the
// mailbox does not look at what is there.
constexpr std::uint32_t kSomewhereOnTheOtherDie = 0x5BA17;

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
  EXPECT_EQ(Read32(registers, UCIE_LINK_EXTENDED_CAPABILITY_HEADER) & 0xFFFFU,
            0x0023U);
}

TEST(WhenTheDvsecHeaderIsRead, ItNamesUcieAsTheVendor) {
  const UcieLinkRegisters registers;

  EXPECT_EQ(Read32(registers, UCIE_LINK_DVSEC_HEADER_1) & 0xFFFFU, 0xD2DEU);
}

TEST(WhenTheRegisterLocatorIsRead, ItSaysWhereTheLinksOwnBlockIs) {
  UcieLinkRegisters registers;
  registers.LinkIs(LinkTrainingState::kSbinit);

  // The first register of the block it points at is where the link says
  // which training state it is in.
  const std::uint64_t block =
      Read32(registers, UCIE_LINK_REGISTER_LOCATOR) >> 8;
  EXPECT_EQ(Read32(registers, block),
            static_cast<std::uint32_t>(LinkTrainingState::kSbinit));
}

TEST(WhenFirmwareAsksForTrainingToStart, TheLinkIsToldToTrain) {
  UcieLinkRegisters registers;

  Write32(registers, UCIE_LINK_CONTROL, UCIE_LINK_CONTROL_START_TRAINING);

  EXPECT_TRUE(registers.TakeCommands().start_training);
}

TEST(WhenFirmwareAsksForARetrain, TheLinkIsToldToTrainAgain) {
  UcieLinkRegisters registers;

  Write32(registers, UCIE_LINK_CONTROL, UCIE_LINK_CONTROL_RETRAIN);

  EXPECT_TRUE(registers.TakeCommands().retrain);
}

TEST(WhenTheControlBitsAreReadBack, TheyHaveClearedThemselves) {
  UcieLinkRegisters registers;
  Write32(registers, UCIE_LINK_CONTROL,
          UCIE_LINK_CONTROL_START_TRAINING | UCIE_LINK_CONTROL_RETRAIN);

  EXPECT_EQ(Read32(registers, UCIE_LINK_CONTROL) &
                (UCIE_LINK_CONTROL_START_TRAINING | UCIE_LINK_CONTROL_RETRAIN),
            0U);
}

TEST(WhenTheLinkIsTraining, TheStatusSaysSoAndNotThatItIsUp) {
  UcieLinkRegisters registers;

  registers.LinkIs(LinkTrainingState::kSbinit);

  EXPECT_EQ(Read32(registers, UCIE_LINK_STATUS) &
                (UCIE_LINK_STATUS_UP | UCIE_LINK_STATUS_TRAINING),
            UCIE_LINK_STATUS_TRAINING);
}

TEST(WhenTheLinkComesUp, TheStatusSaysItIsUpAndThatItChanged) {
  UcieLinkRegisters registers;

  registers.LinkIs(LinkTrainingState::kActive);

  EXPECT_EQ(Read32(registers, UCIE_LINK_STATUS) &
                (UCIE_LINK_STATUS_UP | UCIE_LINK_STATUS_CHANGED),
            UCIE_LINK_STATUS_UP | UCIE_LINK_STATUS_CHANGED);
}

TEST(WhenFirmwareWritesAOneToTheChangedBit, ItIsCleared) {
  UcieLinkRegisters registers;
  registers.LinkIs(LinkTrainingState::kActive);

  Write32(registers, UCIE_LINK_STATUS, UCIE_LINK_STATUS_CHANGED);

  EXPECT_EQ(Read32(registers, UCIE_LINK_STATUS) & UCIE_LINK_STATUS_CHANGED, 0U);
}

TEST(WhenTheLinkChangesAndTheInterruptIsEnabled, TheEndpointInterrupts) {
  UcieLinkRegisters registers;
  Write32(registers, UCIE_LINK_EVENT_NOTIFICATION,
          UCIE_LINK_EVENT_NOTIFICATION_STATUS_CHANGED);

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

  Write32(registers, UCIE_LINK_DIE_RESET, 0);

  EXPECT_FALSE(registers.ResetAsserted());
}

TEST(WhenFirmwareTriggersTheMailbox, ItAsksForThatRegisterOfTheOtherDie) {
  UcieLinkRegisters registers;
  Write32(registers, UCIE_LINK_MAILBOX_OPCODE,
          static_cast<std::uint32_t>(SidebandOpcode::kMemoryRead32b));
  Write32(registers, UCIE_LINK_MAILBOX_ADDRESS, kSomewhereOnTheOtherDie);

  Write32(registers, UCIE_LINK_MAILBOX_TRIGGER, 1);

  const std::optional<MailboxRequest> request =
      registers.TakeCommands().mailbox;
  EXPECT_EQ(request, (MailboxRequest{.opcode = SidebandOpcode::kMemoryRead32b,
                                     .address = kSomewhereOnTheOtherDie}));
}

TEST(WhenAMailboxRequestIsTriggered, TheStatusSaysItIsWaitingForAnAnswer) {
  UcieLinkRegisters registers;

  Write32(registers, UCIE_LINK_MAILBOX_TRIGGER, 1);

  EXPECT_EQ(Read32(registers, UCIE_LINK_MAILBOX_STATUS) &
                UCIE_LINK_MAILBOX_STATUS_BUSY,
            UCIE_LINK_MAILBOX_STATUS_BUSY);
}

TEST(WhenAMailboxRequestIsAnswered, TheStatusStopsSayingItIsWaiting) {
  UcieLinkRegisters registers;
  Write32(registers, UCIE_LINK_MAILBOX_TRIGGER, 1);

  registers.MailboxAnswered(SidebandStatus::kSuccess, 0);

  EXPECT_EQ(Read32(registers, UCIE_LINK_MAILBOX_STATUS) &
                UCIE_LINK_MAILBOX_STATUS_BUSY,
            0U);
}

TEST(WhenAMailboxRequestIsAnswered, ItsDataAndStatusAreThereToRead) {
  UcieLinkRegisters registers;

  registers.MailboxAnswered(SidebandStatus::kSuccess, 0xC0FF'EE00);

  EXPECT_EQ(Read32(registers, UCIE_LINK_MAILBOX_DATA), 0xC0FF'EE00U);
  EXPECT_EQ(Read32(registers, UCIE_LINK_MAILBOX_STATUS),
            static_cast<std::uint32_t>(SidebandStatus::kSuccess));
}

TEST(WhenFirmwareInjectsAFault, TheLinkIsToldToFault) {
  UcieLinkRegisters registers;

  Write32(registers, UCIE_LINK_FAULT_INJECTION, 1);

  EXPECT_TRUE(registers.TakeCommands().fault);
}

TEST(WhenAnAccessToTheBlockIsNot32BitsWide, ItIsRefused) {
  UcieLinkRegisters registers;
  std::array<std::uint8_t, 2> half{};

  EXPECT_FALSE(registers.ReadRegister(UCIE_LINK_STATUS, half));
}

TEST(WhenAnAccessStartsPastTheEndOfTheBlock, ItIsRefused) {
  UcieLinkRegisters registers;

  EXPECT_FALSE(Write32(registers, UCIE_LINK_SIZE, 1));
}

TEST(WhenTheRegistersAreRead, TheyAskNothingOfTheLink) {
  UcieLinkRegisters registers;
  Read32(registers, UCIE_LINK_CONTROL);
  Read32(registers, UCIE_LINK_MAILBOX_TRIGGER);
  Read32(registers, UCIE_LINK_FAULT_INJECTION);

  const UcieLinkRegisters::Commands commands = registers.TakeCommands();

  EXPECT_FALSE(commands.start_training || commands.retrain || commands.fault ||
               commands.mailbox.has_value());
}

}  // namespace
}  // namespace socpuppet
