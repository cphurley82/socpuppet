#ifndef SOCPUPPET_CORE_NVME_FRONTEND_LOGIC_H_
#define SOCPUPPET_CORE_NVME_FRONTEND_LOGIC_H_

#include <cstddef>
#include <cstdint>
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

 private:
  NvmeHostRegisters host_registers_;
  NvmeQueues queues_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NVME_FRONTEND_LOGIC_H_
