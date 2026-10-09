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

  // Does what there is to do in the host's memory: fetches the next
  // command, if the CPU is not still busy with the last. Returns whether
  // it did anything.
  bool Step();

 private:
  NvmeHostRegisters host_registers_;
  NvmeQueues queues_;
  // Whether the firmware has said it is ready for the host's commands.
  bool ready_ = false;
  // What the host has done that the CPU has not yet acknowledged.
  std::uint32_t events_ = 0;
  // The command the CPU is to deal with next, if there is one. There is
  // room for one: the next is fetched when this one's completion has been
  // posted.
  std::optional<NvmeQueues::Command> command_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NVME_FRONTEND_LOGIC_H_
