#ifndef SOCPUPPET_MODELS_BORROWED_MODEL_H_
#define SOCPUPPET_MODELS_BORROWED_MODEL_H_

// What the adapters around VPV-Peripherals' models have in common. Like
// the borrowed headers themselves, this is for an adapter's source file
// only: it includes SCC.

#include <scc/utilities.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

namespace socpuppet {

// A borrowed model with its power-on reset done. Its registers hold
// whatever was in memory until they are reset, and it resets them only
// when its reset line moves, which in an adapter it never does. So they
// are reset as the simulation starts, once every port is bound.
template <typename Borrowed>
struct PoweredOn : Borrowed {
  using Borrowed::Borrowed;

  void start_of_simulation() override {
    this->regs->reset_start();
    this->regs->reset_stop();
  }
};

// An adapter's way to a borrowed model's registers. The model takes its
// accesses on a socket with a bus width of zero, SCC's mark for "loosely
// timed", and such a socket only binds to its like. This holds the
// initiator of that kind and passes a transaction through it.
class RegistersOf {
 public:
  template <typename TargetSocket>
  explicit RegistersOf(TargetSocket& registers) {
    socket_.bind(registers);
  }

  void Access(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    socket_->b_transport(transaction, delay);
  }

  // Debug transport: no simulated time. Returns the bytes transferred.
  unsigned DebugAccess(tlm::tlm_generic_payload& transaction) {
    return socket_->transport_dbg(transaction);
  }

 private:
  tlm_utils::simple_initiator_socket<RegistersOf, scc::LT> socket_{
      "to_registers"};
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_BORROWED_MODEL_H_
