#include "socpuppet/core/ucie_link_state.h"

#include <chrono>
#include <cstdint>
#include <optional>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "socpuppet/core/time.h"
#include "socpuppet/core/ucie_sideband.h"

namespace socpuppet {
namespace {

using std::chrono_literals::operator""ms;
using std::chrono_literals::operator""us;
using ::testing::ElementsAre;

// Training a link takes a millisecond here, so each of UCIe's four states
// on the way up takes 250 us of it.
constexpr Picoseconds kTraining = 1ms;
constexpr Picoseconds kQuarter = 250us;
// UCIe holds a link in reset for 4 ms before training can begin.
constexpr Picoseconds kUp = 4ms + kTraining;

// Whether there is a die on the other end of the sideband listening.
enum class TheOtherDie { kAnswers, kNeverAnswers };

// The two dies' state machines, with a clock and a sideband between them.
// Delivering a packet takes no time here: what this is about is which
// state each side is in, and when.
class TwoDies {
 public:
  explicit TwoDies(TheOtherDie other = TheOtherDie::kAnswers) : other_(other) {}

  const UcieLinkState& DieA() const { return a_; }
  const UcieLinkState& DieB() const { return b_; }

  // What firmware on one die or the other does, at the moment the clock
  // has reached.
  void TrainA() { a_.StartTraining(now_), Settle(); }
  void TrainB() { b_.StartTraining(now_), Settle(); }
  void FaultA() { a_.Fault(now_), Settle(); }
  void RetrainA() { a_.Retrain(now_), Settle(); }

  // Moves the clock to `when`, stopping at every moment either side asked
  // to be looked at again and carrying the packets between them.
  void RunTo(Picoseconds when) {
    while (true) {
      Settle();
      const std::optional<Picoseconds> next = NextMoment();
      if (!next || *next > when) break;
      now_ = *next;
    }
    now_ = when;
    Settle();
  }

  // The messages die A sent, in the order it sent them, since they were
  // last forgotten.
  const std::vector<SidebandMessage>& MessagesFromA() const { return from_a_; }
  void ForgetMessages() { from_a_.clear(); }

 private:
  // Lets both sides act at the current moment, and carries what they say
  // to each other, until neither has anything more to say.
  void Settle() {
    // No exchange between the two dies is more than four messages deep (a
    // request, its response, the request that follows from it, and its
    // response), and one more look is what shows they have finished. More
    // than that and they are talking in circles.
    constexpr int kDeepestExchange = 4;
    for (int pass = 0; pass <= kDeepestExchange; ++pass) {
      a_.Advance(now_);
      b_.Advance(now_);
      const std::vector<SidebandPacket> from_a = a_.TakeOutgoing();
      const std::vector<SidebandPacket> from_b = b_.TakeOutgoing();
      if (from_a.empty() && from_b.empty()) return;
      for (const SidebandPacket& packet : from_a) {
        from_a_.push_back(MessageIn(packet));
        if (other_ == TheOtherDie::kAnswers) b_.Receive(packet, now_);
      }
      for (const SidebandPacket& packet : from_b) a_.Receive(packet, now_);
    }
    FAIL() << "the two sides never stopped talking at " << now_.count()
           << " ps";
  }

  std::optional<Picoseconds> NextMoment() {
    const std::optional<Picoseconds> from_a = a_.Advance(now_);
    const std::optional<Picoseconds> from_b = b_.Advance(now_);
    if (!from_a) return from_b;
    if (!from_b) return from_a;
    return *from_a < *from_b ? from_a : from_b;
  }

  static SidebandMessage MessageIn(const SidebandPacket& packet) {
    return {
        .code = packet.msgcode,
        .subcode = packet.msgsubcode,
        .carries_data = packet.opcode == SidebandOpcode::kMessageWith64bData};
  }

  TheOtherDie other_;
  UcieLinkState a_{kTraining};
  UcieLinkState b_{kTraining};
  Picoseconds now_{};
  std::vector<SidebandMessage> from_a_;
};

TEST(WhenALinkIsPoweredOn, ItIsInReset) {
  const TwoDies dies;

  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kReset);
}

TEST(WhenTrainingIsAskedForDuringTheResetHold, TheLinkIsStillInReset) {
  TwoDies dies;
  dies.TrainA();

  dies.RunTo(4ms - Picoseconds{1});

  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kReset);
}

TEST(WhenALinkTrains, ItWalksUciesStatesAQuarterOfTheTrainingTimeEach) {
  TwoDies dies;
  dies.TrainA();

  dies.RunTo(4ms);
  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kSbinit);
  dies.RunTo(4ms + kQuarter);
  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kMbinit);
  dies.RunTo(4ms + 2 * kQuarter);
  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kMbtrain);
  dies.RunTo(4ms + 3 * kQuarter);
  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kLinkinit);
  dies.RunTo(kUp);
  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kActive);
}

TEST(WhenOneDieTrainsTheLink, TheOtherDieComesUpToo) {
  TwoDies dies;
  dies.TrainA();

  dies.RunTo(kUp);

  EXPECT_EQ(dies.DieB().State(), LinkTrainingState::kActive);
}

TEST(WhenOneDieTrainsTheLink, TheOtherIsInTheSameStateAllTheWayUp) {
  TwoDies dies;
  dies.TrainA();

  for (std::uint64_t quarters = 0; quarters <= 4; ++quarters) {
    dies.RunTo(4ms + quarters * kQuarter);
    EXPECT_EQ(dies.DieB().State(), dies.DieA().State())
        << quarters << " quarters of the training in";
  }
}

TEST(WhenALinkComesUp, TheMessagesGoInUciesOrder) {
  TwoDies dies;
  dies.TrainA();

  dies.RunTo(kUp);

  EXPECT_THAT(dies.MessagesFromA(),
              ElementsAre(kSbinitOutOfReset, kSbinitDoneRequest,
                          kMbinitParamConfigurationRequest,
                          kMbinitCalDoneRequest, kLinkMgmtRdiRequestActive));
}

TEST(WhenBothDiesAreToldToTrainTheLink, EachStateIsAskedForOnlyOnce) {
  TwoDies dies;
  dies.TrainA();
  dies.TrainB();

  dies.RunTo(kUp);

  // The same five requests as when one die drives the training, each with
  // this die's answer to the other's identical request beside it. Nothing
  // walks a state twice.
  EXPECT_THAT(
      dies.MessagesFromA(),
      ElementsAre(kSbinitOutOfReset, kSbinitDoneRequest, kSbinitDoneResponse,
                  kMbinitParamConfigurationRequest,
                  kMbinitParamConfigurationResponse, kMbinitCalDoneRequest,
                  kMbinitCalDoneResponse, kLinkMgmtRdiRequestActive,
                  kLinkMgmtRdiResponseActive));
}

TEST(WhenBothDiesAreToldToTrainTheLink, BothComeUp) {
  TwoDies dies;
  dies.TrainA();
  dies.TrainB();

  dies.RunTo(kUp);

  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kActive);
  EXPECT_EQ(dies.DieB().State(), LinkTrainingState::kActive);
}

TEST(WhenTheOtherDieNeverAnswers, TrainingEndsInAnError) {
  TwoDies dies{TheOtherDie::kNeverAnswers};
  dies.TrainA();

  // SBINIT begins 4 ms in, and UCIe gives a state 8 ms to be answered.
  dies.RunTo(4ms + 8ms);

  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kTrainError);
}

TEST(WhenALinkFaultsWhileActive, BothDiesGoDown) {
  TwoDies dies;
  dies.TrainA();
  dies.RunTo(kUp);

  dies.FaultA();

  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kTrainError);
  EXPECT_EQ(dies.DieB().State(), LinkTrainingState::kTrainError);
}

TEST(WhenALinkFaultsWhileActive, ItSaysOnTheSidebandWhatWentWrong) {
  TwoDies dies;
  dies.TrainA();
  dies.RunTo(kUp);
  dies.ForgetMessages();

  dies.FaultA();

  EXPECT_THAT(dies.MessagesFromA(),
              ElementsAre(kLinkMgmtRdiRequestLinkError, kErrorMessageFatal));
}

TEST(WhenAFaultedLinkIsRetrained, BothDiesComeUpAgain) {
  TwoDies dies;
  dies.TrainA();
  dies.RunTo(kUp);
  dies.FaultA();

  dies.RetrainA();
  dies.RunTo(kUp + 4ms + kTraining);

  EXPECT_EQ(dies.DieA().State(), LinkTrainingState::kActive);
  EXPECT_EQ(dies.DieB().State(), LinkTrainingState::kActive);
}

}  // namespace
}  // namespace socpuppet
