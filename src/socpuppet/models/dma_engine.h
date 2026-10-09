#ifndef SOCPUPPET_MODELS_DMA_ENGINE_H_
#define SOCPUPPET_MODELS_DMA_ENGINE_H_

#include <systemc>
#include <tlm_utils/simple_initiator_socket.h>

#include "socpuppet/core/dma_engine_logic.h"
#include "socpuppet/models/command_device.h"
#include "socpuppet/models/socket_memory.h"

namespace socpuppet {

// The part of an SSD's controller that moves data between the host's
// memory and the SSD's own. The SSD's CPU says where in each and how many
// bytes, and the engine copies them, one way or the other. This is the
// SystemC wrapper, and the logic is in DmaEngineLogic.
//
// `cpu` is its register block and `irq` its interrupt line (see
// CommandDevice). `host` is how it reads and writes the host's memory, and
// `local` the SSD's own.
class DmaEngine : public CommandDevice<DmaEngineLogic> {
 public:
  tlm_utils::simple_initiator_socket<DmaEngine> host{"host"};
  tlm_utils::simple_initiator_socket<DmaEngine> local{"local"};

  explicit DmaEngine(const sc_core::sc_module_name& name)
      : CommandDevice(name, logic_) {}

 private:
  using Initiator = tlm_utils::simple_initiator_socket<DmaEngine>;

  // The two memories, as the logic reaches them.
  SocketMemory<Initiator> host_memory_{host};
  SocketMemory<Initiator> local_memory_{local};
  DmaEngineLogic logic_{host_memory_, local_memory_};
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_DMA_ENGINE_H_
