#include "socpuppet/core/ucie_link_state.h"

#include <chrono>
#include <cstdint>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "socpuppet/core/time.h"
#include "socpuppet/core/ucie_sideband.h"
#include "tests/cpp/support/sideband_pump.h"

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

// The two dies' state machines, with the pump between them. A is the die
// whose firmware manages the link.
class TwoDies {
 public:
  explicit TwoDies(TheOtherEnd other = TheOtherEnd::kAnswers)
      : pump_(a_, b_, other) {}

  const UcieLinkState& DieA() const { return a_; }
  const UcieLinkState& DieB() const { return b_; }

  // What firmware on one die or the other does, at the moment the clock
  // has reached.
  void TrainA() { a_.StartTraining(pump_.Now()), pump_.Settle(); }
  void TrainB() { b_.StartTraining(pump_.Now()), pump_.Settle(); }
  void FaultA() { a_.Fault(pump_.Now()), pump_.Settle(); }
  void RetrainA() { a_.Retrain(pump_.Now()), pump_.Settle(); }

  void RunTo(Picoseconds when) { pump_.RunTo(when); }
  const std::vector<SidebandMessage>& MessagesFromA() const {
    return pump_.MessagesFromA();
  }
  void ForgetMessages() { pump_.ForgetMessages(); }

 private:
  UcieLinkState a_{kTraining};
  UcieLinkState b_{kTraining};
  SidebandPump<UcieLinkState> pump_;
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
  TwoDies dies{TheOtherEnd::kNeverAnswers};
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
