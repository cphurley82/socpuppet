#include "socpuppet/core/d2d_link_logic.h"

#include <array>
#include <chrono>
#include <cstdint>
#include <ios>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/time.h"
#include "socpuppet/core/ucie_sideband.h"
#include "socpuppet/regs/ucie_link.h"
#include "tests/cpp/support/sideband_pump.h"

namespace socpuppet {
namespace {

using std::chrono_literals::operator""ms;
using std::chrono_literals::operator""ns;

// A link that takes this long and this many bytes a nanosecond to cross,
// and a millisecond to train.
constexpr Picoseconds kLatency = 20ns;
constexpr std::uint64_t kBytesPerNs = 16;
constexpr Picoseconds kTraining = 1ms;

// One link: an end on each die, with the pump between them. A is the die
// whose firmware manages the link.
class OneLink {
 public:
  D2dLinkLogic& A() { return a_; }
  D2dLinkLogic& B() { return b_; }

  // Firmware on die A reading and writing its own link registers, and
  // what the far end's look like from outside.
  std::uint32_t Read(std::uint64_t offset) { return Read(a_, offset); }
  void Write(std::uint64_t offset, std::uint32_t value) {
    a_.WriteRegister(offset, LittleEndianBytes(value));
    pump_.Settle();
  }
  std::uint32_t ReadOnB(std::uint64_t offset) { return Read(b_, offset); }

  // Two writes with nothing in between, as firmware running ahead of the
  // clock makes them: the link is handed both at once.
  void WriteBoth(std::uint64_t first, std::uint32_t first_value,
                 std::uint64_t second, std::uint32_t second_value) {
    a_.WriteRegister(first, LittleEndianBytes(first_value));
    a_.WriteRegister(second, LittleEndianBytes(second_value));
    pump_.Settle();
  }

  void RunUntilNothingIsDue() { pump_.RunUntilNothingIsDue(); }

 private:
  static std::uint32_t Read(const D2dLinkLogic& end, std::uint64_t offset) {
    std::array<std::uint8_t, 4> bytes{};
    EXPECT_TRUE(end.ReadRegister(offset, bytes))
        << "the read of 0x" << std::hex << offset << " was refused";
    return LoadLittleEndian<std::uint32_t>(bytes);
  }

  D2dLinkLogic a_{kLatency, kBytesPerNs, kTraining};
  D2dLinkLogic b_{kLatency, kBytesPerNs, kTraining};
  SidebandPump<D2dLinkLogic> pump_{a_, b_};
};

// Fills the mailbox in and triggers it, as firmware does.
void AskTheOtherDie(OneLink& link, SidebandOpcode opcode, std::uint32_t address,
                    std::uint32_t data = 0) {
  link.Write(UCIE_LINK_MAILBOX_OPCODE,
             static_cast<std::uint32_t>(opcode)
                 << UCIE_LINK_MAILBOX_OPCODE_CODE_SHIFT);
  link.Write(UCIE_LINK_MAILBOX_ADDRESS, address);
  link.Write(UCIE_LINK_MAILBOX_DATA, data);
  link.Write(UCIE_LINK_MAILBOX_TRIGGER, UCIE_LINK_MAILBOX_TRIGGER_GO);
}

TEST(WhenFirmwareStartsTrainingThroughTheRegisters, TheLinkComesUp) {
  OneLink link;

  link.Write(UCIE_LINK_CONTROL, UCIE_LINK_CONTROL_START_TRAINING);
  link.RunUntilNothingIsDue();

  EXPECT_EQ(link.Read(UCIE_LINK_STATUS) & UCIE_LINK_STATUS_UP,
            UCIE_LINK_STATUS_UP);
}

TEST(WhenALinkHasNotBeenTrained, ItsMainbandCarriesNothing) {
  OneLink link;

  link.RunUntilNothingIsDue();

  EXPECT_FALSE(link.A().IsActive());
}

TEST(WhenTheManagerWritesTheOtherDiesResetRegister, ThatDieIsLetGo) {
  OneLink link;

  AskTheOtherDie(link, SidebandOpcode::kMemoryWrite32b, UCIE_LINK_DIE_RESET, 0);

  EXPECT_FALSE(link.B().ResetAsserted());
}

TEST(WhenTheManagerReadsARegisterOfTheOtherDie, TheAnswerIsInItsMailbox) {
  OneLink link;

  AskTheOtherDie(link, SidebandOpcode::kMemoryRead32b, UCIE_LINK_DIE_RESET);

  // The other die is holding its own die in reset, as it does until it is
  // let go.
  EXPECT_EQ(link.Read(UCIE_LINK_MAILBOX_DATA), 1U);
  EXPECT_EQ(link.Read(UCIE_LINK_MAILBOX_STATUS),
            static_cast<std::uint32_t>(SidebandStatus::kSuccess));
}

TEST(WhenTheManagerAsksForARegisterTheOtherDieHasNot, TheMailboxSaysSo) {
  OneLink link;

  AskTheOtherDie(link, SidebandOpcode::kMemoryRead32b,
                 static_cast<std::uint32_t>(UCIE_LINK_SIZE));

  EXPECT_EQ(link.Read(UCIE_LINK_MAILBOX_STATUS),
            static_cast<std::uint32_t>(SidebandStatus::kUnsupportedRequest));
}

TEST(WhenFirmwareInjectsAFaultAndAsksForARetrainAtOnce, TheLinkComesBackUp) {
  OneLink link;
  link.Write(UCIE_LINK_CONTROL, UCIE_LINK_CONTROL_START_TRAINING);
  link.RunUntilNothingIsDue();

  link.WriteBoth(UCIE_LINK_FAULT_INJECTION, 1, UCIE_LINK_CONTROL,
                 UCIE_LINK_CONTROL_RETRAIN);
  link.RunUntilNothingIsDue();

  EXPECT_EQ(link.Read(UCIE_LINK_STATUS) & UCIE_LINK_STATUS_UP,
            UCIE_LINK_STATUS_UP);
}

TEST(WhenFirmwareInjectsAFault, TheOtherDiesStatusShowsAFatalError) {
  OneLink link;
  link.Write(UCIE_LINK_CONTROL, UCIE_LINK_CONTROL_START_TRAINING);
  link.RunUntilNothingIsDue();

  link.Write(UCIE_LINK_FAULT_INJECTION, 1);

  EXPECT_EQ(
      link.ReadOnB(UCIE_LINK_STATUS) & UCIE_LINK_STATUS_UNCORRECTABLE_FATAL,
      UCIE_LINK_STATUS_UNCORRECTABLE_FATAL);
}

TEST(WhenEachEndIsAskedWhatACrossingCosts, ItAnswersForItsOwnDirection) {
  OneLink link;
  // Traffic leaving the other die occupies the link the other way, which
  // is not this end's to wait for.
  link.B().Cross(64, Picoseconds{0});

  EXPECT_EQ(link.A().Cross(64, Picoseconds{0}),
            kLatency + Picoseconds{std::uint64_t{64} * 1000 / kBytesPerNs});
}

}  // namespace
}  // namespace socpuppet
