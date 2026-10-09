#ifndef SOCPUPPET_CORE_NVME_CONTROLLER_H_
#define SOCPUPPET_CORE_NVME_CONTROLLER_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>

#include "socpuppet/core/block_store.h"
#include "socpuppet/core/interrupt_requests.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/nvme_host_registers.h"
#include "socpuppet/core/nvme_queues.h"

// The layout of a command. It is SPDK's (nvme_spec.h), and only
// nvme_controller.cpp includes it.
struct spdk_nvme_cmd;  // NOLINT(readability-identifier-naming)

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
  // `blocks` is how many blocks its one namespace holds, and `vectors`
  // how many interrupt vectors it has. The drive is kept in RAM, zeros
  // until written.
  NvmeController(MemoryPort& host_memory, std::uint64_t blocks,
                 std::size_t vectors);
  // The same, with the drive the caller gives it.
  NvmeController(MemoryPort& host_memory, std::unique_ptr<BlockStore> drive,
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

  // What the controller asks of the host on its interrupt vectors.
  InterruptRequests& HostInterrupts() { return queues_; }

 private:
  // How a command went: what its completion will say.
  using Outcome = NvmeQueues::Outcome;
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

  // The blocks a read or a write is for.
  struct BlockRange {
    std::uint64_t first = 0;
    std::uint64_t count = 0;
  };
  // The blocks the command names, or nothing if any of them is past the
  // end of the drive.
  std::optional<BlockRange> BlocksOf(const spdk_nvme_cmd& command) const;

  MemoryPort& host_memory_;
  std::size_t vectors_;
  // What the drive holds.
  std::unique_ptr<BlockStore> drive_;

  // The register block.
  NvmeHostRegisters registers_;

  // The queues. The admin queues are set up from the registers above when
  // the controller is enabled, and the host sets up each I/O queue with an
  // admin command.
  NvmeQueues queues_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NVME_CONTROLLER_H_
