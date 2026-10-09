#ifndef SOCPUPPET_CORE_NVME_FRONTEND_LOGIC_H_
#define SOCPUPPET_CORE_NVME_FRONTEND_LOGIC_H_

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>

#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/nvme_host_registers.h"
#include "socpuppet/core/nvme_queues.h"

namespace socpuppet {

// What the NVMe frontend of an SSD's controller does, with no simulator
// attached. It is the hardware between the host and the SSD's firmware: it
// keeps the queues, and the firmware makes the decisions.
//
// It has two register blocks. The host's is an NVMe controller's, as the
// specification gives it. The other is for the SSD's own CPU, which reads
// each command the frontend has fetched and says what its completion is.
class NvmeFrontendLogic {
 public:
  // `vectors` is how many interrupt vectors it has for the host.
  NvmeFrontendLogic(MemoryPort& host_memory, std::size_t vectors);

  // Reads and writes of the host's register block. Each returns false, and
  // touches nothing, if the access is refused.
  bool ReadHostRegister(std::uint64_t offset,
                        std::span<std::uint8_t> out) const;
  bool WriteHostRegister(std::uint64_t offset,
                         std::span<const std::uint8_t> in);

  // Reads and writes of the register block of the SSD's own CPU.
  bool ReadCpuRegister(std::uint64_t offset, std::span<std::uint8_t> out) const;
  bool WriteCpuRegister(std::uint64_t offset, std::span<const std::uint8_t> in);

  // Does what there is to do in the host's memory: posts the completion
  // the CPU has asked for, and fetches the next command if the CPU is not
  // still busy with the last. Returns whether it did anything.
  bool Step();

  // What the frontend asks of the host on its interrupt vectors.
  InterruptRequests& HostInterrupts() { return queues_; }

 private:
  // Whether there is a command the CPU has yet to deal with: one has been
  // fetched, and the CPU has not asked for its completion to be posted.
  bool CommandWaiting() const { return command_ && !posting_; }

  // Creates the queue the queue registers describe, of the kind the
  // queue-create register was told. Returns false if it cannot be.
  bool CreateQueue(std::uint32_t kind);

  NvmeHostRegisters host_registers_;
  NvmeQueues queues_;
  // How many interrupt vectors the frontend has for the host.
  std::size_t vectors_;
  // Whether the firmware has said it is ready for the host's commands.
  bool ready_ = false;
  // What the host has done that the CPU has not yet acknowledged.
  std::uint32_t events_ = 0;
  // The command the CPU is to deal with next, if there is one. There is
  // room for one: the next is fetched when this one's completion has been
  // posted.
  std::optional<NvmeQueues::Command> command_;
  // What the completion of that command is to say, as the CPU wrote it,
  // and whether the CPU has asked for it to be posted.
  std::uint32_t completion_result_ = 0;
  std::uint32_t completion_status_ = 0;
  bool posting_ = false;
  // The queue registers, as the CPU wrote them.
  struct QueueRegisters {
    std::uint32_t id = 0;
    std::uint64_t base = 0;
    std::uint32_t last = 0;
    std::uint32_t link = 0;
  };
  QueueRegisters queue_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NVME_FRONTEND_LOGIC_H_
