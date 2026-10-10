#include "socpuppet/core/ucie_link_state.h"

#include <algorithm>
#include <optional>
#include <utility>
#include <vector>

#include "socpuppet/core/time.h"
#include "socpuppet/core/ucie_sideband.h"

namespace socpuppet {

void UcieLinkState::StartTraining(Picoseconds now) {
  driving_ = true;
  walking_ = true;
  asked_at_ = now;
}

void UcieLinkState::Retrain(Picoseconds now) {
  Send(kLinkMgmtRdiRequestRetrain);
  driving_ = true;
  asked_at_ = now;
  Enter(LinkTrainingState::kReset, now);
}

void UcieLinkState::Fault(Picoseconds now) {
  Send(kLinkMgmtRdiRequestLinkError);
  Send(kErrorMessageFatal);
  Enter(LinkTrainingState::kTrainError, now);
}

std::vector<SidebandPacket> UcieLinkState::TakeOutgoing() {
  return std::exchange(outgoing_, {});
}

std::optional<Picoseconds> UcieLinkState::Advance(Picoseconds now) {
  while (true) {
    const std::optional<Picoseconds> due = Due();
    if (!due || *due > now) return due;
    // A state is entered when it was due, not when this was called, so
    // that a late look does not stretch the training out.
    Enter(awaiting_ ? LinkTrainingState::kTrainError : After(state_), *due);
  }
}

std::optional<Picoseconds> UcieLinkState::Due() const {
  if (awaiting_) return awaiting_since_ + kAnswerTimeout;
  if (!walking_) return std::nullopt;
  switch (state_) {
    case LinkTrainingState::kReset:
      // The hold is counted from power-on, but firmware that asks after it
      // is over is not training a link that came up in the past.
      return std::max(entered_at_ + kResetHold, asked_at_);
    case LinkTrainingState::kSbinit:
    case LinkTrainingState::kMbinit:
    case LinkTrainingState::kMbtrain:
    case LinkTrainingState::kLinkinit:
      return entered_at_ + Quarter();
    case LinkTrainingState::kActive:
    case LinkTrainingState::kTrainError:
      return std::nullopt;
  }
  return std::nullopt;
}

LinkTrainingState UcieLinkState::After(LinkTrainingState state) {
  switch (state) {
    case LinkTrainingState::kReset:
      return LinkTrainingState::kSbinit;
    case LinkTrainingState::kSbinit:
      return LinkTrainingState::kMbinit;
    case LinkTrainingState::kMbinit:
      return LinkTrainingState::kMbtrain;
    case LinkTrainingState::kMbtrain:
      return LinkTrainingState::kLinkinit;
    case LinkTrainingState::kLinkinit:
      return LinkTrainingState::kActive;
    case LinkTrainingState::kActive:
    case LinkTrainingState::kTrainError:
      return state;
  }
  return state;
}

void UcieLinkState::Enter(LinkTrainingState state, Picoseconds now) {
  state_ = state;
  entered_at_ = now;
  awaiting_.reset();
  // A link in reset goes nowhere until its own firmware asks or the other
  // die says it has left reset.
  if (state == LinkTrainingState::kReset) walking_ = driving_;
  if (!driving_) return;
  switch (state) {
    case LinkTrainingState::kSbinit:
      // The other die hears that this one is out of reset, and is asked to
      // agree that the sideband is up.
      Send(kSbinitOutOfReset);
      Send(kSbinitDoneRequest);
      Await(kSbinitDoneResponse, now);
      break;
    case LinkTrainingState::kMbinit:
      Send(kMbinitParamConfigurationRequest);
      Await(kMbinitParamConfigurationResponse, now);
      break;
    case LinkTrainingState::kLinkinit:
      Send(kLinkMgmtRdiRequestActive);
      Await(kLinkMgmtRdiResponseActive, now);
      break;
    case LinkTrainingState::kReset:
    case LinkTrainingState::kMbtrain:
    case LinkTrainingState::kActive:
    case LinkTrainingState::kTrainError:
      break;
  }
}

void UcieLinkState::Send(const SidebandMessage& message) {
  // The configuration messages have room for what the two sides can do,
  // and nothing here is negotiated: both ends are the same link. The data
  // they carry is zero, which is what a trace will show.
  outgoing_.push_back(MessagePacket(message, SidebandAgent::kD2dAdapter,
                                    SidebandAgent::kD2dAdapter));
}

void UcieLinkState::Await(const SidebandMessage& message, Picoseconds now) {
  awaiting_ = message;
  awaiting_since_ = now;
}

void UcieLinkState::Receive(const SidebandPacket& packet, Picoseconds now) {
  const SidebandMessage message = MessageIn(packet);
  if (awaiting_ && message == *awaiting_) {
    awaiting_.reset();
    // MBINIT has two exchanges: what the two sides can do, and then that
    // the mainband has been calibrated.
    if (message == kMbinitParamConfigurationResponse) {
      Send(kMbinitCalDoneRequest);
      Await(kMbinitCalDoneResponse, now);
    }
    return;
  }
  Answer(message, now);
}

void UcieLinkState::Answer(const SidebandMessage& request, Picoseconds now) {
  if (request == kSbinitOutOfReset) {
    // The other die is driving the training. This one walks the same
    // states beside it, from the same moment.
    if (state_ == LinkTrainingState::kReset) {
      walking_ = true;
      Enter(LinkTrainingState::kSbinit, now);
    }
  } else if (request == kSbinitDoneRequest) {
    Send(kSbinitDoneResponse);
  } else if (request == kMbinitParamConfigurationRequest) {
    Send(kMbinitParamConfigurationResponse);
  } else if (request == kMbinitCalDoneRequest) {
    Send(kMbinitCalDoneResponse);
  } else if (request == kLinkMgmtRdiRequestActive) {
    Send(kLinkMgmtRdiResponseActive);
  } else if (request == kLinkMgmtRdiRequestLinkError) {
    Enter(LinkTrainingState::kTrainError, now);
  } else if (request == kLinkMgmtRdiRequestRetrain) {
    Enter(LinkTrainingState::kReset, now);
  }
}

}  // namespace socpuppet
