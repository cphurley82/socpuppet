#ifndef SOCPUPPET_CORE_NVME_CONTROLLER_H_
#define SOCPUPPET_CORE_NVME_CONTROLLER_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

// The layouts of the controller registers and of a command. They are
// SPDK's (nvme_spec.h), and only nvme_controller.cpp includes it.
struct spdk_nvme_registers;  // NOLINT(readability-identifier-naming)
struct spdk_nvme_cmd;        // NOLINT(readability-identifier-naming)

namespace socpuppet {

// What an NVMe controller does, with no simulator attached: the registers a
// host driver talks to, and the commands it carries out.
//
// A host and a controller talk through queues that live in the host's
// memory. The host writes a 64-byte command into a submission queue and
// then writes the queue's new tail to a doorbell register. The controller
// fetches the command, carries it out, writes a 16-byte completion into a
// completion queue, and the host writes that queue's new head to another
// doorbell once it has read the completion.
//
// It follows the NVMe base specification, which is public. The layouts of
// the registers, commands and completions come from SPDK's nvme_spec.h.
class NvmeController {
 public:
  // The host's memory, which the controller reads and writes on its own
  // initiative (direct memory access, DMA). Each returns false if the host
  // did not take the access: nothing is at the address, say.
  class HostMemory {
   public:
    virtual ~HostMemory() = default;
    virtual bool Read(std::uint64_t address, std::span<std::uint8_t> out) = 0;
    virtual bool Write(std::uint64_t address,
                       std::span<const std::uint8_t> in) = 0;
  };

  // `blocks` is how many blocks its one namespace holds, and `vectors`
  // how many interrupt vectors it has.
  NvmeController(HostMemory& host_memory, std::uint64_t blocks,
                 std::size_t vectors);

  // Reads from the register block, the way a host reads the memory behind
  // BAR0. Returns false, and touches nothing, if nothing readable is there.
  // The doorbells are write-only.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const;

  // Writes to the register block: a controller register, or a doorbell.
  // Returns false if nothing is there to take the write: no such register,
  // the doorbell of a queue that does not exist, or a doorbell value that
  // is not a slot of its queue. A doorbell only records what the host
  // wrote, and the command is carried out by CarryOutOne().
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in);

  // Carries out one command the host has submitted, if there is one:
  // fetches it from the host's memory, does what it says and posts its
  // completion there. Returns false if there was nothing to do.
  bool CarryOutOne();

  // Whether the controller is asking for the host's attention on one of
  // its interrupt vectors: a completion queue that uses the vector holds a
  // completion the host has not yet acknowledged.
  //
  // When the host acknowledges completions (by writing the queue's head
  // doorbell), the queue stops asking, even if more completions are
  // waiting, and starts again at the next Rearm(). The host is told about
  // an interrupt when the line rises, so a line that just stayed high for
  // the completions still waiting would tell it nothing.
  //
  // Each completion queue is expected to have a vector to itself. Two
  // queues on one vector would hold the line up for each other.
  bool Interrupting(std::size_t vector) const;

  // Whether an acknowledgement has quieted a queue since the last Rearm().
  bool Quieted() const;

  // Lets queues that were quieted by an acknowledgement ask again. Call it
  // only once the host has had the chance to see the line low: rearming in
  // the same step as the acknowledgement would hide the fall.
  void Rearm();

 private:
  // How many I/O queue pairs the host may create. A real controller has a
  // fixed number too, because each queue costs it a set of pointers and a
  // pair of doorbell registers.
  static constexpr std::uint16_t kIoQueuePairs = 8;
  // Queue 0 of each kind is the admin queue, and the I/O queues follow.
  static constexpr std::size_t kQueues = 1 + kIoQueuePairs;

  // A submission queue: commands, which the host writes and the controller
  // fetches. Like every queue here it is a ring in the host's memory.
  struct SubmissionQueue {
    // The admin queue exists while the controller is enabled. An I/O queue
    // exists once the host has created it with an admin command.
    bool exists = false;
    // Where it is in the host's memory.
    std::uint64_t base = 0;
    // Its last slot. Queue sizes are given counted from zero, and a
    // 65536-entry queue's last slot fits in 16 bits where its size does not.
    std::uint16_t last = 0;
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
    std::uint64_t base = 0;
    std::uint16_t last = 0;
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

  // How a command went: what its completion will say.
  struct Outcome {
    // The status code, which is zero for success, and which list of codes
    // it is from: the generic one (type 0) or the command's own (type 1).
    std::uint8_t status = 0;
    std::uint8_t status_type = 0;
    // The command's answer, for the few commands that have one that fits
    // in 32 bits (the completion's first dword).
    std::uint32_t result = 0;
  };
  // A failure with a status from the list that belongs to the command,
  // and not from the generic one.
  static Outcome CommandSpecific(std::uint8_t status);

  // Moves a command's data to the host's memory, where the command says it
  // goes, or fetches it from there. The outcome is success, or a data
  // transfer error if the host did not take some of it.
  Outcome SendToHost(const spdk_nvme_cmd& command,
                     std::span<const std::uint8_t> data);
  Outcome FetchFromHost(const spdk_nvme_cmd& command,
                        std::span<std::uint8_t> data);

  // The registers as the host would read them now.
  spdk_nvme_registers Registers() const;
  bool RingDoorbell(std::uint64_t offset, std::span<const std::uint8_t> in);
  // What setting and clearing CC.EN do.
  void Enable();
  void Reset();

  // Does what an admin command says, whichever command it is.
  Outcome CarryOutAdmin(const spdk_nvme_cmd& command);
  // The admin commands, one each.
  Outcome CreateIoCompletionQueue(const spdk_nvme_cmd& command);
  Outcome CreateIoSubmissionQueue(const spdk_nvme_cmd& command);
  Outcome Identify(const spdk_nvme_cmd& command);
  Outcome SetFeatures(const spdk_nvme_cmd& command);

  // Does what an I/O command says, whichever command it is.
  Outcome CarryOutIo(const spdk_nvme_cmd& command);
  // The I/O commands, one each.
  Outcome Read(const spdk_nvme_cmd& command);
  Outcome Write(const spdk_nvme_cmd& command);

  // The part of the drive a read or a write covers, or nothing if any of
  // it is past the end.
  std::span<std::uint8_t> Blocks(const spdk_nvme_cmd& command);

  HostMemory& host_memory_;
  std::uint64_t blocks_;
  std::size_t vectors_;
  // What the drive holds: every block, in RAM, zeros until written.
  std::vector<std::uint8_t> drive_;

  // Registers, as the host last wrote them: CC (the configuration), AQA
  // (how long the admin queues are), and ASQ and ACQ (where they are).
  std::uint32_t configuration_ = 0;
  std::uint32_t admin_queue_sizes_ = 0;
  std::uint64_t admin_submission_queue_ = 0;
  std::uint64_t admin_completion_queue_ = 0;

  // The queues, by identifier. The admin queues are set up from the
  // registers above when the controller is enabled, and the host sets up
  // each I/O queue with an admin command.
  std::array<SubmissionQueue, kQueues> submissions_;
  std::array<CompletionQueue, kQueues> completions_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NVME_CONTROLLER_H_
