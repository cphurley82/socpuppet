#include "socpuppet/core/d2d_link_logic.h"

#include <array>
#include <chrono>
#include <cstdint>
#include <optional>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/time.h"
#include "socpuppet/core/ucie_sideband.h"

namespace socpuppet {
namespace {

using std::chrono_literals::operator""ms;
using std::chrono_literals::operator""ns;

// A link that takes this long and this many bytes a nanosecond to cross,
// and a millisecond to train.
constexpr Picoseconds kLatency = 20ns;
constexpr std::uint64_t kBytesPerNs = 16;
constexpr Picoseconds kTraining = 1ms;

// Where the registers are, and which bits are which, is the register
// block's own business: these tests are about what the three parts do
// together.
using Registers = UcieLinkRegisters;

// One link: an end on each die, with a sideband between them and a clock.
// A is the die whose firmware manages the link.
class OneLink {
 public:
  D2dLinkLogic& A() { return a_; }
  D2dLinkLogic& B() { return b_; }

  // Firmware on die A reading and writing its own link registers.
  std::uint32_t Read(std::uint64_t offset) { return Read(a_, offset); }
  void Write(std::uint64_t offset, std::uint32_t value) {
    a_.WriteRegister(offset, LittleEndianBytes(value));
    Settle();
  }
  std::uint32_t ReadOnB(std::uint64_t offset) { return Read(b_, offset); }

  // Lets the clock run on, stopping wherever either end asked to be looked
  // at again and carrying the sideband packets between them, until there
  // is nothing more either of them is waiting for.
  void RunUntilNothingIsDue() {
    while (true) {
      Settle();
      const std::optional<Picoseconds> next = NextMoment();
      if (!next) return;
      ASSERT_GT(*next, now_) << "an end asked to be looked at in the past";
      now_ = *next;
    }
  }

 private:
  static std::uint32_t Read(const D2dLinkLogic& end, std::uint64_t offset) {
    std::array<std::uint8_t, 4> bytes{};
    end.ReadRegister(offset, bytes);
    return LoadLittleEndian<std::uint32_t>(bytes);
  }

  void Settle() {
    // No exchange between the two ends is more than four messages deep (a
    // request, its answer, the request that follows from it, and its
    // answer), and one more look is what shows they have finished.
    constexpr int kDeepestExchange = 4;
    for (int pass = 0; pass <= kDeepestExchange; ++pass) {
      a_.Advance(now_);
      b_.Advance(now_);
      const std::vector<SidebandPacket> from_a = a_.TakeOutgoing();
      const std::vector<SidebandPacket> from_b = b_.TakeOutgoing();
      if (from_a.empty() && from_b.empty()) return;
      for (const SidebandPacket& packet : from_a) b_.Receive(packet, now_);
      for (const SidebandPacket& packet : from_b) a_.Receive(packet, now_);
    }
    FAIL() << "the two ends never stopped talking at " << now_.count() << " ps";
  }

  std::optional<Picoseconds> NextMoment() {
    const std::optional<Picoseconds> from_a = a_.Advance(now_);
    const std::optional<Picoseconds> from_b = b_.Advance(now_);
    if (!from_a) return from_b;
    if (!from_b) return from_a;
    return *from_a < *from_b ? from_a : from_b;
  }

  D2dLinkLogic a_{kLatency, kBytesPerNs, kTraining};
  D2dLinkLogic b_{kLatency, kBytesPerNs, kTraining};
  Picoseconds now_{};
};

// Fills the mailbox in and triggers it, as firmware does.
void AskTheOtherDie(OneLink& link, SidebandOpcode opcode, std::uint32_t address,
                    std::uint32_t data = 0) {
  link.Write(Registers::kMailboxOpcode, static_cast<std::uint32_t>(opcode));
  link.Write(Registers::kMailboxAddress, address);
  link.Write(Registers::kMailboxData, data);
  link.Write(Registers::kMailboxTrigger, 1);
}

TEST(WhenFirmwareStartsTrainingThroughTheRegisters, TheLinkComesUp) {
  OneLink link;

  link.Write(Registers::kLinkControl, Registers::kStartTraining);
  link.RunUntilNothingIsDue();

  EXPECT_EQ(link.Read(Registers::kLinkStatusRegister) & Registers::kLinkUp,
            Registers::kLinkUp);
}

TEST(WhenALinkHasNotBeenTrained, ItsMainbandCarriesNothing) {
  OneLink link;

  link.RunUntilNothingIsDue();

  EXPECT_FALSE(link.A().IsActive());
}

TEST(WhenTheManagerWritesTheOtherDiesResetRegister, ThatDieIsLetGo) {
  OneLink link;

  AskTheOtherDie(link, SidebandOpcode::kMemoryWrite32b, Registers::kDieReset,
                 0);

  EXPECT_FALSE(link.B().ResetAsserted());
}

TEST(WhenTheManagerReadsARegisterOfTheOtherDie, TheAnswerIsInItsMailbox) {
  OneLink link;

  AskTheOtherDie(link, SidebandOpcode::kMemoryRead32b, Registers::kDieReset);

  // The other die is holding its own die in reset, as it does until it is
  // let go.
  EXPECT_EQ(link.Read(Registers::kMailboxData), 1U);
  EXPECT_EQ(link.Read(Registers::kMailboxStatus),
            static_cast<std::uint32_t>(SidebandStatus::kSuccess));
}

TEST(WhenTheManagerAsksForARegisterTheOtherDieHasNot, TheMailboxSaysSo) {
  OneLink link;

  AskTheOtherDie(link, SidebandOpcode::kMemoryRead32b,
                 static_cast<std::uint32_t>(UcieLinkRegisters::kSize));

  EXPECT_EQ(link.Read(Registers::kMailboxStatus),
            static_cast<std::uint32_t>(SidebandStatus::kUnsupportedRequest));
}

TEST(WhenFirmwareInjectsAFault, TheOtherDiesStatusShowsAFatalError) {
  OneLink link;
  link.Write(Registers::kLinkControl, Registers::kStartTraining);
  link.RunUntilNothingIsDue();

  link.Write(Registers::kFaultInjection, 1);

  EXPECT_EQ(link.ReadOnB(Registers::kLinkStatusRegister) &
                Registers::kDetectedUncorrectableFatal,
            Registers::kDetectedUncorrectableFatal);
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
