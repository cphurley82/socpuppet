#ifndef SPIKES_NPU_ACCELERATOR_SLOT_H_
#define SPIKES_NPU_ACCELERATOR_SLOT_H_

#include <systemc>
#include <tlm>

namespace spike {

// The draft of an accelerator slot (milestone M12). An accelerator is a
// block the host hands work to: the host writes a description of the work
// into memory, tells the block where it is through a register block, and
// is interrupted when the block is done. So the slot has three things:
//
//   `socket`  a bus master, through which the block reads the work's
//             description and its operands and writes its result;
//   `cpu`     its register block, as the host's CPU sees it;
//   `irq`     one interrupt line towards the host.
//
// This is the DMA engine's shape (socpuppet/models/dma_engine.h) with one
// memory in place of two, and it is what both of the spike's candidates
// are held to. The register block is the doorbell's (doorbell.h), so that
// the firmware's side is the same for both. The real slot, if M19 keeps
// this one, goes into socpuppet/platform/slots.h.
template <typename T>
concept AcceleratorSlot = requires(T accelerator) {
  { accelerator.socket } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
  { accelerator.cpu } -> std::convertible_to<tlm::tlm_target_socket<>&>;
  { accelerator.irq } -> std::convertible_to<sc_core::sc_out<bool>&>;
};

}  // namespace spike

#endif  // SPIKES_NPU_ACCELERATOR_SLOT_H_
