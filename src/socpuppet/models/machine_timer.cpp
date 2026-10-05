#include "socpuppet/models/machine_timer.h"

#include <cstdint>
#include <memory>

#include <minres/aclint.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

namespace socpuppet {

// The borrowed timer and what it needs around it. It learns its tick from a
// signal that carries the tick's period. It has one more interrupt output,
// the software interrupt, which a CPU raises on another CPU and which
// nobody reads here. Its reset is never asserted.
struct MachineTimer::Model {
  Model(MachineTimer& owner, std::uint64_t frequency_hz)
      : tick_period_("tick_period",
                     sc_core::sc_time(1.0 / static_cast<double>(frequency_hz),
                                      sc_core::SC_SEC)) {
    to_registers_.bind(timer_.socket);
    timer_.mtime_clk_i.bind(tick_period_);
    timer_.rst_i.bind(reset_tied_low_);
    timer_.mtime_int_o[0].bind(owner.irq);
    timer_.msip_int_o[0].bind(software_interrupt_unread_);
  }

  void AccessRegister(tlm::tlm_generic_payload& transaction,
                      sc_core::sc_time& delay) {
    to_registers_->b_transport(transaction, delay);
  }

 private:
  sc_core::sc_signal<sc_core::sc_time> tick_period_;
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  sc_core::sc_signal<bool> software_interrupt_unread_{
      "software_interrupt_unread"};
  // One CPU.
  vpvper::minres::aclint timer_{"timer", 1};
  // The model's socket has a bus width of zero, SCC's mark for "loosely
  // timed", and only binds to its like.
  tlm_utils::simple_initiator_socket<Model, scc::LT> to_registers_{
      "to_registers"};
};

MachineTimer::MachineTimer(const sc_core::sc_module_name& name,
                           std::uint64_t frequency_hz)
    : sc_module(name), model_(std::make_unique<Model>(*this, frequency_hz)) {
  socket.register_b_transport(this, &MachineTimer::b_transport);
}

MachineTimer::~MachineTimer() = default;

void MachineTimer::b_transport(tlm::tlm_generic_payload& transaction,
                               sc_core::sc_time& delay) {
  model_->AccessRegister(transaction, delay);
}

}  // namespace socpuppet
