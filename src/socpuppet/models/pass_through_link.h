#pragma once

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// Stand-in for the die-to-die link: passes every transaction on unchanged,
// with no delay.
class PassThroughLink : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<PassThroughLink> target{"target"};
  tlm_utils::simple_initiator_socket<PassThroughLink> initiator{"initiator"};

  explicit PassThroughLink(const sc_core::sc_module_name& name) : sc_module(name) {
    target.register_b_transport(this, &PassThroughLink::b_transport);
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    initiator->b_transport(transaction, delay);
  }
};

}  // namespace socpuppet
