#ifndef TESTS_CPP_SUPPORT_SIDEBAND_PUMP_H_
#define TESTS_CPP_SUPPORT_SIDEBAND_PUMP_H_

#include <optional>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/time.h"
#include "socpuppet/core/ucie_sideband.h"

// Whether there is anything on the other end of the sideband listening.
enum class TheOtherEnd { kAnswers, kNeverAnswers };

// A clock and a sideband between the two ends of a die-to-die link, for
// the parts of it that run without a simulator. Either end is anything
// that is told the time, says when it next wants to be looked at, and
// hands over the packets it wants sent:
//
//   std::optional<socpuppet::Picoseconds> Advance(Picoseconds now);
//   void Receive(const socpuppet::SidebandPacket& packet, Picoseconds now);
//   std::vector<socpuppet::SidebandPacket> TakeOutgoing();
//
// Delivering a packet takes no time here. What a test built on this is
// about is what each end does, and when.
template <typename End>
class SidebandPump {
 public:
  SidebandPump(End& a, End& b, TheOtherEnd other = TheOtherEnd::kAnswers)
      : a_(a), b_(b), other_(other) {}

  socpuppet::Picoseconds Now() const { return now_; }

  // Lets both ends act at the moment the clock has reached, and carries
  // what they say to each other, until neither has anything more to say.
  void Settle() {
    // No exchange between the two ends is more than four messages deep (a
    // request, its answer, the request that follows from it, and its
    // answer), and one more look is what shows they have finished.
    constexpr int kDeepestExchange = 4;
    for (int pass = 0; pass <= kDeepestExchange; ++pass) {
      a_.Advance(now_);
      b_.Advance(now_);
      const std::vector<socpuppet::SidebandPacket> from_a = a_.TakeOutgoing();
      const std::vector<socpuppet::SidebandPacket> from_b = b_.TakeOutgoing();
      if (from_a.empty() && from_b.empty()) return;
      for (const socpuppet::SidebandPacket& packet : from_a) {
        from_a_.push_back(socpuppet::MessageIn(packet));
        if (other_ == TheOtherEnd::kAnswers) b_.Receive(packet, now_);
      }
      for (const socpuppet::SidebandPacket& packet : from_b) {
        a_.Receive(packet, now_);
      }
    }
    FAIL() << "the two ends never stopped talking at " << now_.count() << " ps";
  }

  // Moves the clock to `when`, stopping at every moment either end asked
  // to be looked at again.
  void RunTo(socpuppet::Picoseconds when) {
    while (true) {
      Settle();
      const std::optional<socpuppet::Picoseconds> next = NextMoment();
      if (!next || *next > when) break;
      ASSERT_GT(*next, now_) << "an end asked to be looked at in the past";
      now_ = *next;
    }
    now_ = when;
    Settle();
  }

  // Lets the clock run on until there is nothing either end is waiting
  // for any more.
  void RunUntilNothingIsDue() {
    while (true) {
      Settle();
      const std::optional<socpuppet::Picoseconds> next = NextMoment();
      if (!next) return;
      ASSERT_GT(*next, now_) << "an end asked to be looked at in the past";
      now_ = *next;
    }
  }

  // The messages the first end sent, in the order it sent them, since
  // they were last forgotten.
  const std::vector<socpuppet::SidebandMessage>& MessagesFromA() const {
    return from_a_;
  }
  void ForgetMessages() { from_a_.clear(); }

 private:
  // The next moment either end asked for, if either did.
  std::optional<socpuppet::Picoseconds> NextMoment() {
    const std::optional<socpuppet::Picoseconds> from_a = a_.Advance(now_);
    const std::optional<socpuppet::Picoseconds> from_b = b_.Advance(now_);
    if (!from_a) return from_b;
    if (!from_b) return from_a;
    return *from_a < *from_b ? from_a : from_b;
  }

  End& a_;
  End& b_;
  TheOtherEnd other_;
  socpuppet::Picoseconds now_{};
  std::vector<socpuppet::SidebandMessage> from_a_;
};

#endif  // TESTS_CPP_SUPPORT_SIDEBAND_PUMP_H_
