#ifndef SOCPUPPET_CORE_NVME_QUEUES_H_
#define SOCPUPPET_CORE_NVME_QUEUES_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>

#include "socpuppet/core/interrupt_requests.h"
#include "socpuppet/core/memory_port.h"

namespace socpuppet {

// The queues of an NVMe controller, with no simulator attached: fetching
// commands from them, posting completions to them, and asking for the
// host's attention when it has completions to read.
//
// A host and a controller talk through queues that live in the host's
// memory. The host writes a 64-byte command into a submission queue and
// then writes the queue's new tail to a doorbell register. The controller
// fetches the command, and once it has been carried out writes a 16-byte
// completion into a completion queue. The host writes that queue's new
// head to another doorbell when it has read the completion.
//
// This is the part every controller does the same way, whoever decides
// what a command means: the stand-in drive, which decides for itself, or
// an SSD's hardware, which hands each command to its firmware.
//
// The layout of a completion comes from SPDK's nvme_spec.h.
class NvmeQueues : public InterruptRequests {
 public:
  // How many I/O queue pairs the host may create. A real controller has a
  // fixed number too, because each queue costs it a set of pointers and a
  // pair of doorbell registers.
  static constexpr std::uint16_t kIoQueuePairs = 8;
  // Queue 0 of each kind is the admin queue, and the I/O queues follow.
  static constexpr std::size_t kQueues = 1 + kIoQueuePairs;
  // How long a command is.
  static constexpr std::size_t kCommandBytes = 64;

  explicit NvmeQueues(MemoryPort& host_memory) : host_memory_(host_memory) {}

  // Where a queue is in the host's memory, and its last slot. Queue sizes
  // are given counted from zero, and a 65536-entry queue's last slot fits
  // in 16 bits where its size does not.
  struct Ring {
    std::uint64_t base = 0;
    std::uint16_t last = 0;
  };

  // Whether a queue exists. The admin queues exist while the controller is
  // enabled, and an I/O queue once the host has had it created. There is
  // no queue with an identifier of kQueues or more.
  bool HasCompletionQueue(std::size_t queue_id) const;
  bool HasSubmissionQueue(std::size_t queue_id) const;

  // Makes a queue exist, empty. `queue_id` is less than kQueues. `vector`
  // is the interrupt vector that tells the host a completion queue has
  // something to read, and `completion_queue` is where the completions of
  // a submission queue's commands go.
  void CreateCompletionQueue(std::size_t queue_id, const Ring& ring,
                             std::uint16_t vector);
  void CreateSubmissionQueue(std::size_t queue_id, const Ring& ring,
                             std::uint16_t completion_queue);

  // Does away with every queue, which is what a controller reset does.
  void RemoveAll();

  // A write to a doorbell. They are numbered in pairs, queue after queue:
  // a submission queue's tail, then the completion queue's head. Returns
  // false, and changes nothing, for a queue that does not exist or a
  // pointer that is not one of the queue's slots.
  bool RingDoorbell(std::uint64_t doorbell, std::uint32_t value);

  // A command, and the submission queue it was fetched from.
  struct Command {
    std::uint16_t queue_id = 0;
    std::array<std::uint8_t, kCommandBytes> bytes{};
  };

  // Fetches the next command that can be carried out, or nothing if there
  // is none. It comes from the lowest-numbered queue that has one, so an
  // admin command goes before any I/O command that is waiting. A command
  // whose completion queue is full has to wait: its completion would land
  // in the slot the host uses to tell full from empty, and the one after
  // it on a completion the host has not acknowledged.
  std::optional<Command> Fetch();

  // How a command went: what its completion will say beyond which command
  // it is for.
  struct Outcome {
    // The status code, which is zero for success, and which list of codes
    // it is from: the generic one (type 0) or the command's own (type 1).
    std::uint8_t status = 0;
    std::uint8_t status_type = 0;
    // The command's answer, for the few commands that have one that fits
    // in 32 bits (the completion's first dword).
    std::uint32_t result = 0;
  };

  // Posts the completion of a command that was fetched, to the completion
  // queue of the queue it came from. There is room, because Fetch() saw to
  // it.
  void Post(const Command& command, const Outcome& outcome);

  // InterruptRequests. The controller is asking on a vector while a
  // completion queue that uses the vector holds a completion the host has
  // not yet acknowledged, and the host acknowledges by writing the queue's
  // head doorbell.
  //
  // Each completion queue is expected to have a vector to itself. Two
  // queues on one vector would hold the line up for each other.
  bool Interrupting(std::size_t vector) const override;
  bool Quieted() const override;
  void Rearm() override;

 private:
  // A submission queue: commands, which the host writes and the controller
  // fetches. Like every queue here it is a ring in the host's memory.
  struct SubmissionQueue {
    bool exists = false;
    Ring ring;
    // Where the controller fetches its next command.
    std::uint16_t head = 0;
    // How far the host has filled the queue (from its doorbell).
    std::uint16_t tail = 0;
    // Which completion queue its commands' completions go to.
    std::uint16_t completion_queue = 0;
  };

  // A completion queue: what became of each command, which the controller
  // writes and the host reads.
  struct CompletionQueue {
    bool exists = false;
    Ring ring;
    // Where the next completion goes.
    std::uint16_t tail = 0;
    // How far the host says it has read (from its doorbell).
    std::uint16_t head = 0;
    // The phase bit the next completion carries. It inverts each time the
    // queue wraps around, which is how the host tells a new completion
    // from the one that was in the slot a lap ago.
    bool phase = true;
    // Which interrupt vector tells the host there is something to read.
    std::uint16_t vector = 0;
    // Whether the host has acknowledged completions since the last Rearm().
    bool quieted = false;
  };

  MemoryPort& host_memory_;
  // The queues, by identifier.
  std::array<SubmissionQueue, kQueues> submissions_;
  std::array<CompletionQueue, kQueues> completions_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NVME_QUEUES_H_
