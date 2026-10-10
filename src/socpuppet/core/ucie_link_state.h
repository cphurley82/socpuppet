#ifndef SOCPUPPET_CORE_UCIE_LINK_STATE_H_
#define SOCPUPPET_CORE_UCIE_LINK_STATE_H_

#include <chrono>
#include <optional>
#include <vector>

#include "socpuppet/core/time.h"
#include "socpuppet/core/ucie_sideband.h"

namespace socpuppet {

// Where a die-to-die link is on its way up. UCIe calls this its link
// training state machine, and these are its states, in the order a link
// walks them:
//
//   RESET ──▶ SBINIT ──▶ MBINIT ──▶ MBTRAIN ──▶ LINKINIT ──▶ ACTIVE
//     ▲          │          │          │           │           │
//     │          └──────────┴──────────┴───────────┴───────────┘
//     │                              │ nobody answered, or a fault
//     └────── retrained ────── TRAINERROR ◀────────┘
//
// RESET is where a link starts and where it waits to be told to train.
// SBINIT brings the sideband up, MBINIT and MBTRAIN the main data path,
// and LINKINIT is where the two dies agree that the link is theirs to
// use. Only in ACTIVE does the mainband carry anything. TRAINERROR is
// where a link that could not be trained, or one that has faulted, waits
// to be trained again.
enum class LinkTrainingState {
  kReset,
  kSbinit,
  kMbinit,
  kMbtrain,
  kLinkinit,
  kActive,
  kTrainError,
};

// One die's half of the link training state machine. The two halves walk
// the states side by side: the one whose firmware asked for training sends
// UCIe's requests, and the other answers them.
//
// It has no clock of its own. It is told what time it is, says when it
// next wants to be looked at, and hands over the packets it has to send.
// After any call, Advance() is the one thing that says when to come back;
// nothing else schedules anything. The model around it is what turns that
// into waiting and transactions.
class UcieLinkState {
 public:
  // `training` is how long SBINIT to ACTIVE takes, a quarter in each of
  // the four states on the way.
  explicit UcieLinkState(Picoseconds training) : training_(training) {}

  LinkTrainingState State() const { return state_; }

  // Firmware has asked for the link to be trained. Training begins once
  // the reset hold is over, which may be now or may have been a while ago.
  void StartTraining(Picoseconds now);
  // Train it again from the beginning, telling the other die to do the
  // same. This is what firmware does with a link that has faulted.
  void Retrain(Picoseconds now);
  // Something has gone wrong with the link: it goes down, and the other
  // die is told.
  void Fault(Picoseconds now);

  // A packet has arrived from the other die.
  void Receive(const SidebandPacket& packet, Picoseconds now);
  // Lets whatever is due at `now` happen, and says when it next wants to
  // be called. Nothing, if it is waiting for nothing but the other die.
  std::optional<Picoseconds> Advance(Picoseconds now);
  // The packets to send to the other die, which it then no longer holds.
  std::vector<SidebandPacket> TakeOutgoing();

 private:
  // UCIe holds a link in RESET for at least 4 ms before training can
  // begin, and gives a state 8 ms to be answered in before giving up.
  static constexpr Picoseconds kResetHold =
      std::chrono::duration_cast<Picoseconds>(std::chrono::milliseconds{4});
  static constexpr Picoseconds kAnswerTimeout =
      std::chrono::duration_cast<Picoseconds>(std::chrono::milliseconds{8});

  // How long each state on the way up lasts.
  Picoseconds Quarter() const { return training_ / 4; }
  // When the current state gives way to the next, or when waiting for the
  // other die runs out of patience. Nothing, if the link is not on its way
  // anywhere.
  std::optional<Picoseconds> Due() const;
  // The state after this one on the way up.
  static LinkTrainingState After(LinkTrainingState state);

  void Enter(LinkTrainingState state, Picoseconds now);
  void Send(const SidebandMessage& message);
  void Await(const SidebandMessage& message, Picoseconds now);
  // Answers a request from the other die.
  void Answer(const SidebandMessage& request, Picoseconds now);

  Picoseconds training_;
  LinkTrainingState state_ = LinkTrainingState::kReset;
  // When the link entered its current state. At power-on that is time
  // zero, which is where the reset hold is counted from.
  Picoseconds entered_at_{};
  // Whether this die's firmware has asked for training, and when. The die
  // that asked is the one that sends the requests.
  bool driving_ = false;
  Picoseconds asked_at_{};
  // Whether this die's walk up the states is under way. Firmware asking
  // starts it, and so does the other die saying it has left reset: both
  // dies then walk the same states at the same times, with the messages
  // as the agreement between them rather than as the clock.
  bool walking_ = false;
  // The response this die is waiting for, and since when.
  std::optional<SidebandMessage> awaiting_;
  Picoseconds awaiting_since_{};
  std::vector<SidebandPacket> outgoing_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_UCIE_LINK_STATE_H_
