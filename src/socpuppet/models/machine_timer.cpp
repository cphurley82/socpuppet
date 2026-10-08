#include "socpuppet/models/machine_timer.h"

#include <cstdint>
#include <memory>

#include <minres/aclint.h>
#include <minres/gen/aclint_regs.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

namespace socpuppet {

namespace {

// The borrowed timer, with its power-on reset done. Its registers hold
// whatever was in memory until they are reset, and it resets them only
// when its reset line moves, which here it never does. So they are reset
// as the simulation starts, once every port is bound.
struct PoweredOnAclint : vpvper::minres::aclint {
  explicit PoweredOnAclint(const sc_core::sc_module_name& name)
      : aclint(name, /*num_cpus=*/1) {}

  void start_of_simulation() override {
    regs->reset_start();
    regs->reset_stop();
  }
};

}  // namespace

// The borrowed timer and what it needs around it. It learns its tick from a
// signal that carries the tick's period. It has one more interrupt output,
// the software interrupt, which a CPU raises on another CPU and which
// nobody reads here. Its reset is never asserted.
struct MachineTimer::Model {
  explicit Model(std::uint64_t frequency_hz)
      : tick_period_("tick_period",
                     sc_core::sc_time(1.0 / static_cast<double>(frequency_hz),
                                      sc_core::SC_SEC)) {
    to_registers_.bind(timer_.socket);
    timer_.mtime_clk_i.bind(tick_period_);
    timer_.rst_i.bind(reset_tied_low_);
    timer_.mtime_int_o[0].bind(interrupt_);
    timer_.msip_int_o[0].bind(software_interrupt_unread_);
  }

  void AccessRegister(tlm::tlm_generic_payload& transaction,
                      sc_core::sc_time& delay) {
    to_registers_->b_transport(transaction, delay);
  }
  unsigned DebugAccessRegister(tlm::tlm_generic_payload& transaction) {
    return to_registers_->transport_dbg(transaction);
  }

  // What the borrowed model says its interrupt output is.
  const sc_core::sc_signal_in_if<bool>& Interrupt() const { return interrupt_; }

 private:
  sc_core::sc_signal<sc_core::sc_time> tick_period_;
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  // The borrowed model writes its output from whichever process is running:
  // its own method when the count reaches the compare value, and the
  // caller's thread when a register is written. SystemC lets one process
  // write a signal in a delta cycle (SC_MANY_WRITERS only lifts that across
  // delta cycles), so this signal is told not to check, and the adapter
  // copies it to `irq` from one process of its own.
  sc_core::sc_signal<bool, sc_core::SC_UNCHECKED_WRITERS> interrupt_{
      "interrupt"};
  sc_core::sc_signal<bool> software_interrupt_unread_{
      "software_interrupt_unread"};
  PoweredOnAclint timer_{"timer"};
  // The model's socket has a bus width of zero, SCC's mark for "loosely
  // timed", and only binds to its like.
  tlm_utils::simple_initiator_socket<Model, scc::LT> to_registers_{
      "to_registers"};
};

MachineTimer::MachineTimer(const sc_core::sc_module_name& name,
                           std::uint64_t frequency_hz)
    : sc_module(name), model_(std::make_unique<Model>(frequency_hz)) {
  socket.register_b_transport(this, &MachineTimer::b_transport);
  socket.register_transport_dbg(this, &MachineTimer::transport_dbg);
  SC_METHOD(DriveTheLine);
  sensitive << model_->Interrupt();
}

void MachineTimer::DriveTheLine() { irq.write(model_->Interrupt().read()); }

unsigned MachineTimer::transport_dbg(tlm::tlm_generic_payload& transaction) {
  return model_->DebugAccessRegister(transaction);
}

MachineTimer::~MachineTimer() = default;

void MachineTimer::b_transport(tlm::tlm_generic_payload& transaction,
                               sc_core::sc_time& delay) {
  model_->AccessRegister(transaction, delay);
}

}  // namespace socpuppet
