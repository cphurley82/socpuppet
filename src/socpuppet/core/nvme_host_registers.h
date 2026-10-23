#ifndef SOCPUPPET_CORE_NVME_HOST_REGISTERS_H_
#define SOCPUPPET_CORE_NVME_HOST_REGISTERS_H_

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>

#include "socpuppet/core/nvme_queues.h"

namespace socpuppet {

// The register block an NVMe controller shows its host, with no simulator
// attached: the controller registers in the first 4 KiB, which this keeps,
// and the doorbells after them, which it only knows how to find.
//
// The host writes four of the registers: CC (the configuration, with the
// enable bit lowest), AQA (how long the admin queues are), and ASQ and ACQ
// (where they are). What the others say is the controller's business, and
// two controllers differ in it, so whoever has one of these says it on
// each read.
//
// The layout is SPDK's (nvme_spec.h), and only the source file includes it.
class NvmeHostRegisters {
 public:
  // How far a shutdown the host asked for has got (CSTS.SHST): none
  // asked for, under way, or complete, by the specification's numbers.
  enum class Shutdown : std::uint8_t {
    kNone = 0,
    kUnderWay = 1,
    kComplete = 2
  };

  // What a controller says for itself in the registers the host only
  // reads.
  struct Says {
    // CAP.TO: the longest the host should wait for the controller to
    // become ready, or to stop being ready, in units of 500 ms.
    std::uint8_t ready_timeout = 0;
    // CSTS.RDY: whether the controller is ready for commands.
    bool ready = false;
    // CSTS.SHST: how far a shutdown the host asked for has got.
    Shutdown shutdown = Shutdown::kNone;
  };

  // Reads from the controller registers. Returns false, and touches
  // nothing, if the read is not all inside them.
  bool Read(std::uint64_t offset, std::span<std::uint8_t> out,
            const Says& says) const;

  // What a write did to the enable bit, CC.EN.
  enum class Enable { kUnchanged, kSet, kCleared };

  // A write to the register block, by the host: to a controller register,
  // or to a doorbell. Returns nothing, and changes nothing, if the write
  // is refused: it is not all inside the controller registers, or it is
  // not a 32-bit write to the doorbell of a queue that exists, with a
  // pointer that is one of the queue's slots. A write to a register the
  // host only reads changes nothing.
  //
  // The queues are whoever's the register block is. A doorbell write goes
  // to them. Setting CC.EN makes the admin queues exist, where AQA, ASQ
  // and ACQ say they are, with the first interrupt vector. Clearing it is
  // a controller reset, which does away with every queue.
  std::optional<Enable> Write(std::uint64_t offset,
                              std::span<const std::uint8_t> in,
                              NvmeQueues& queues);

  // Whether a write to `offset` is to a completion queue's head doorbell,
  // by which the host acknowledges completions.
  static bool IsCompletionHeadDoorbell(std::uint64_t offset);

  // Whether the host has the controller enabled: CC.EN.
  bool Enabled() const;

  // Whether the host has asked the controller to shut down: CC.SHN.
  bool ShutdownAsked() const;

 private:
  // A write to the controller registers, and what it did to CC.EN.
  std::optional<Enable> WriteControllerRegister(
      std::uint64_t offset, std::span<const std::uint8_t> in);
  void CreateAdminQueues(NvmeQueues& queues) const;

  // As the host last wrote them.
  std::uint32_t configuration_ = 0;
  std::uint32_t admin_queue_sizes_ = 0;
  std::uint64_t admin_submission_queue_ = 0;
  std::uint64_t admin_completion_queue_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NVME_HOST_REGISTERS_H_
