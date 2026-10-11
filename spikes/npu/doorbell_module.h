#ifndef SPIKES_NPU_DOORBELL_MODULE_H_
#define SPIKES_NPU_DOORBELL_MODULE_H_

#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "spikes/npu/doorbell.h"

namespace spike {

// The doorbell as a block on the bus, for a candidate whose work is done
// by a core of its own (the Hexagon). The host has the register block at
// `cpu` and the interrupt at `irq`. The core has the same block at
// `accelerator`, where it reads PENDING and the descriptor's address and
// writes COMPLETE, and `kick` is high while a command is pending, which
// is what goes into the core's interrupt controller. Two sockets rather
// than one, because the host and the core are on different buses in every
// placing M12 considers.
//
// The behavioral candidate does not need this: its shell is the DMA
// engine's (socpuppet/models/command_device.h) and its work is done
// in-process. Both use DoorbellLogic, which is the point.
class Doorbell : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Doorbell> cpu{"cpu"};
  tlm_utils::simple_target_socket<Doorbell> accelerator{"accelerator"};
  sc_core::sc_out<bool> irq{"irq"};
  sc_core::sc_out<bool> kick{"kick"};

  explicit Doorbell(const sc_core::sc_module_name& name) : sc_module(name) {
    cpu.register_b_transport(this, &Doorbell::b_transport);
    cpu.register_transport_dbg(this, &Doorbell::transport_dbg);
    accelerator.register_b_transport(this, &Doorbell::b_transport);
    accelerator.register_transport_dbg(this, &Doorbell::transport_dbg);
    SC_METHOD(DriveTheLines);
    sensitive << lines_may_have_changed_;
    dont_initialize();
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    const bool ok = transaction.is_read()
                        ? logic_.ReadRegister(transaction.get_address(), data)
                        : logic_.WriteRegister(transaction.get_address(), data);
    transaction.set_response_status(ok ? tlm::TLM_OK_RESPONSE
                                       : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    if (transaction.is_write()) lines_may_have_changed_.notify();
  }

  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    return transaction.is_read() &&
                   logic_.ReadRegister(transaction.get_address(), data)
               ? transaction.get_data_length()
               : 0;
  }

  void DriveTheLines() {
    irq.write(logic_.Interrupting());
    kick.write(logic_.Pending() != 0);
  }

  DoorbellLogic logic_;
  sc_core::sc_event lines_may_have_changed_;
};

}  // namespace spike

#endif  // SPIKES_NPU_DOORBELL_MODULE_H_
