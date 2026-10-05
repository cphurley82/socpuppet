#include "socpuppet/models/plic.h"

#include <algorithm>
#include <cstddef>
#include <memory>

#include <rvi/plic.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

namespace socpuppet {

namespace {

// The borrowed PLIC, with one context and with its power-on reset done.
// Its registers hold whatever was in memory until they are reset, and it
// resets them only when its reset line moves, which here it never does. So
// they are reset as the simulation starts, once every port is bound.
struct PoweredOnPlic : vpvper::rvi::plic<Plic::kSources, 1> {
  explicit PoweredOnPlic(const sc_core::sc_module_name& name) : plic(name) {}

  void start_of_simulation() override {
    regs->reset_start();
    regs->reset_stop();
  }
};

}  // namespace

// The borrowed PLIC and what it needs around it. It has one "context", a
// CPU and privilege mode that can be interrupted: ours is the one CPU in
// machine mode. Its reset is never asserted, and its clock input only sets
// how long a register access is said to take, which we leave at no time.
struct Plic::Model {
  explicit Model(Plic& owner) {
    to_registers_.bind(plic_.socket);
    plic_.clk_i.bind(access_time_);
    plic_.rst_i.bind(reset_tied_low_);
    for (std::size_t source = 0; source < kSources; ++source) {
      plic_.interrupts_i[source].bind(owner.sources[source]);
    }
    plic_.interrupts_o[0].bind(owner.irq);
  }

  void AccessRegister(tlm::tlm_generic_payload& transaction,
                      sc_core::sc_time& delay) {
    to_registers_->b_transport(transaction, delay);
  }

 private:
  sc_core::sc_signal<sc_core::sc_time> access_time_{"access_time"};
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  PoweredOnPlic plic_{"plic"};
  // The model's socket has a bus width of zero, SCC's mark for "loosely
  // timed", and only binds to its like.
  tlm_utils::simple_initiator_socket<Model, scc::LT> to_registers_{
      "to_registers"};
};

Plic::Plic(const sc_core::sc_module_name& name)
    : sc_module(name), model_(std::make_unique<Model>(*this)) {
  socket.register_b_transport(this, &Plic::b_transport);
}

Plic::~Plic() = default;

void Plic::before_end_of_elaboration() {
  for (auto& source : sources) {
    if (source.size() == 0) source.bind(tied_low_);
  }
}

void Plic::b_transport(tlm::tlm_generic_payload& transaction,
                       sc_core::sc_time& delay) {
  model_->AccessRegister(transaction, delay);
  // The PLIC's register map has room for 1,023 sources and thousands of
  // contexts. The parts this PLIC has no use for are reserved: they read as
  // zero and ignore writes. A driver may touch them without asking first,
  // as Zephyr's does when it clears the enable bits, and the borrowed model
  // answers such an access with an error.
  if (transaction.get_response_status() == tlm::TLM_ADDRESS_ERROR_RESPONSE) {
    if (transaction.is_read()) {
      std::fill_n(transaction.get_data_ptr(), transaction.get_data_length(),
                  static_cast<unsigned char>(0));
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }
}

}  // namespace socpuppet
