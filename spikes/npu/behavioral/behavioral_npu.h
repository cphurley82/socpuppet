#ifndef SPIKES_NPU_BEHAVIORAL_BEHAVIORAL_NPU_H_
#define SPIKES_NPU_BEHAVIORAL_BEHAVIORAL_NPU_H_

#include <systemc>
#include <tlm_utils/simple_initiator_socket.h>

#include "socpuppet/models/command_device.h"
#include "socpuppet/models/socket_memory.h"
#include "spikes/npu/accelerator_slot.h"
#include "spikes/npu/behavioral/multiplier.h"
#include "spikes/npu/behavioral/npu_logic.h"

namespace spike {

// 🎭 The behavioral NPU behind the draft accelerator slot: the doorbell's
// registers at `cpu`, its reads and writes of memory through `socket`,
// its interrupt at `irq`, and the arithmetic done by whichever Multiplier
// it is handed. The SystemC shell is the DMA engine's.
class BehavioralNpu : public socpuppet::CommandDevice<NpuLogic> {
 public:
  tlm_utils::simple_initiator_socket<BehavioralNpu> socket{"socket"};

  BehavioralNpu(const sc_core::sc_module_name& name, Multiplier& multiplier)
      : CommandDevice(name, logic_), logic_(memory_, multiplier) {}

 private:
  using Initiator = tlm_utils::simple_initiator_socket<BehavioralNpu>;

  socpuppet::SocketMemory<Initiator> memory_{socket};
  NpuLogic logic_;
};

static_assert(AcceleratorSlot<BehavioralNpu>);

}  // namespace spike

#endif  // SPIKES_NPU_BEHAVIORAL_BEHAVIORAL_NPU_H_
