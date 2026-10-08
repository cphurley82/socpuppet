#include "socpuppet/models/plic.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <memory>

#include <rvi/plic.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

#include "socpuppet/models/borrowed_model.h"
#include "socpuppet/models/tie_low.h"

namespace socpuppet {

// The borrowed PLIC and what it needs around it. It has one "context", a
// CPU and privilege mode that can be interrupted: ours is the one CPU in
// machine mode. Its reset is never asserted, and its clock input only sets
// how long a register access is said to take, which we leave at no time.
struct Plic::Model {
  explicit Model(Plic& owner) {
    plic_.clk_i.bind(access_time_);
    plic_.rst_i.bind(reset_tied_low_);
    for (std::size_t source = 0; source < kSources; ++source) {
      plic_.interrupts_i[source].bind(owner.sources[source]);
    }
    plic_.interrupts_o[0].bind(interrupt_);
  }

  // What the borrowed model says its interrupt output is.
  const sc_core::sc_signal_in_if<bool>& Interrupt() const { return interrupt_; }

 private:
  sc_core::sc_signal<sc_core::sc_time> access_time_{"access_time"};
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  // The borrowed model writes its output from whichever process is running:
  // its own method when a source's line rises, and the caller's thread
  // when a register is written. SystemC lets one process write a signal in
  // a delta cycle (SC_MANY_WRITERS only lifts that across delta cycles),
  // so this signal is told not to check, and the adapter copies it to `irq`
  // from one process of its own.
  sc_core::sc_signal<bool, sc_core::SC_UNCHECKED_WRITERS> interrupt_{
      "interrupt"};
  // One context.
  PoweredOn<vpvper::rvi::plic<kSources, 1>> plic_{"plic"};

 public:
  RegistersOf registers{plic_.socket};
};

Plic::Plic(const sc_core::sc_module_name& name)
    : sc_module(name), model_(std::make_unique<Model>(*this)) {
  socket.register_b_transport(this, &Plic::b_transport);
  socket.register_transport_dbg(this, &Plic::transport_dbg);
  SC_METHOD(DriveTheLine);
  sensitive << model_->Interrupt();
}

void Plic::DriveTheLine() { irq.write(model_->Interrupt().read()); }

unsigned Plic::transport_dbg(tlm::tlm_generic_payload& transaction) {
  // Reading the claim register claims, and the borrowed model does that
  // for a debug access as well (see docs/upstream.md), so a debugger is
  // not allowed to look. The register is context 0's, 4 bytes past the
  // context's threshold, as the PLIC lays it out.
  constexpr std::uint64_t kClaimComplete = 0x20'0000 + 4;
  constexpr std::uint64_t kRegisterSize = 4;
  if (transaction.get_address() - kClaimComplete < kRegisterSize) return 0;
  return model_->registers.DebugAccess(transaction);
}

Plic::~Plic() = default;

void Plic::before_end_of_elaboration() {
  TieLowIfUnconnected(sources, tied_low_);
}

void Plic::b_transport(tlm::tlm_generic_payload& transaction,
                       sc_core::sc_time& delay) {
  model_->registers.Access(transaction, delay);
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
