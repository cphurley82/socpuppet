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
  // What a controller says for itself in the registers the host only
  // reads.
  struct Says {
    // CAP.TO: the longest the host should wait for the controller to
    // become ready, or to stop being ready, in units of 500 ms.
    std::uint8_t ready_timeout = 0;
    // CSTS.RDY: whether the controller is ready for commands.
    bool ready = false;
  };

  // Reads from the controller registers. Returns false, and touches
  // nothing, if the read is not all inside them.
  bool Read(std::uint64_t offset, std::span<std::uint8_t> out,
            const Says& says) const;

  // What a write did to the enable bit, CC.EN.
  enum class Enable { kUnchanged, kSet, kCleared };

  // Writes to the controller registers. A write to a register the host
  // only reads changes nothing. Returns nothing, and changes nothing, if
  // the write is not all inside them.
  std::optional<Enable> Write(std::uint64_t offset,
                              std::span<const std::uint8_t> in);

  // Makes the admin queues exist, where AQA, ASQ and ACQ say they are. The
  // admin completion queue's interrupt vector is the first.
  void CreateAdminQueues(NvmeQueues& queues) const;

  // Whether an offset is past the controller registers, in the doorbells.
  static bool IsInTheDoorbells(std::uint64_t offset);

  // A write to a doorbell: which one, counting from the first, and the
  // queue pointer the host wrote.
  struct Doorbell {
    std::uint64_t number = 0;
    std::uint32_t value = 0;
  };
  // What a write in the doorbells is, or nothing if it is not a 32-bit
  // write to one of them.
  static std::optional<Doorbell> DoorbellWrite(
      std::uint64_t offset, std::span<const std::uint8_t> in);

 private:
  // As the host last wrote them.
  std::uint32_t configuration_ = 0;
  std::uint32_t admin_queue_sizes_ = 0;
  std::uint64_t admin_submission_queue_ = 0;
  std::uint64_t admin_completion_queue_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NVME_HOST_REGISTERS_H_
