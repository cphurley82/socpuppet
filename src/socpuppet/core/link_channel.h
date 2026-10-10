#ifndef SOCPUPPET_CORE_LINK_CHANNEL_H_
#define SOCPUPPET_CORE_LINK_CHANNEL_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>

#include "socpuppet/core/time.h"

namespace socpuppet {

// One direction of a die-to-die link's main data path (its "mainband"),
// as far as time is concerned. A link has two of these, because each
// direction has wires of its own and the two do not hold each other up.
//
// Two things make a crossing take time. The latency is how long the link
// takes to carry anything at all from one die to the other, and the width
// of the link decides how long its bytes take to go: a transaction's bytes
// follow one another, and the next transaction's wait their turn. So a
// transaction leaving while the link is busy arrives later than one
// leaving an idle link, even though the link's latency is the same.
//
// It knows nothing of the simulator's clock: it is told when a transaction
// leaves and says when it arrives. It is not a SystemC channel, whatever
// its name: it holds no events and runs no processes, and the endpoint
// model is what turns the arrival time it gives back into a delay on a
// transaction.
//
// ⚠️ Transactions take the link in the order they are handed to it, which
// is the order the simulator happened to run their initiators in and not
// the order of their departure times. Under loose timing a master may run
// ahead of the clock, so a transaction handed over second can have left
// first; it still waits for the first one's bytes.
class LinkChannel {
 public:
  // `bytes_per_ns` is how many bytes the link carries in a nanosecond.
  LinkChannel(Picoseconds latency, std::uint64_t bytes_per_ns)
      : latency_(latency), bytes_per_ns_(bytes_per_ns) {}

  // When a transaction of `bytes` that leaves at `departure` arrives on
  // the other die, the link having carried everything handed to it so far.
  Picoseconds Cross(std::size_t bytes, Picoseconds departure) {
    const Picoseconds start = std::max(departure, free_at_);
    free_at_ = start + TimeFor(bytes);
    return free_at_ + latency_;
  }

 private:
  // How long `bytes` take to go. Rounded up to a whole picosecond, which
  // is as fine as time is counted here: no byte has crossed before its
  // time is up.
  Picoseconds TimeFor(std::size_t bytes) const {
    constexpr std::uint64_t kPicosecondsPerNanosecond = 1'000;
    const std::uint64_t picoseconds =
        static_cast<std::uint64_t>(bytes) * kPicosecondsPerNanosecond;
    return Picoseconds{(picoseconds + bytes_per_ns_ - 1) / bytes_per_ns_};
  }

  Picoseconds latency_;
  std::uint64_t bytes_per_ns_;
  // When the last byte handed to it so far has left this die. The
  // crossing's own latency comes after that.
  Picoseconds free_at_{};
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_LINK_CHANNEL_H_
