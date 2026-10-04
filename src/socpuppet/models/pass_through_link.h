#pragma once

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// Stand-in for one end of the die-to-die link. A link is two of these, one
// on each die, with their peer sockets bound to each other.
//
// It passes every transaction straight on, in both directions, with no
// delay, no training and no errors. What it keeps from the real link is the
// shape: one endpoint per die, and traffic that can flow either way.
//
//   this die                                    the other die
//   target ──────────▶ peer_initiator ════▶ peer_target ──────▶ initiator
//   initiator ◀─────── peer_target    ◀════ peer_initiator ◀─── target
class PassThroughLinkEndpoint : public sc_core::sc_module {
 public:
  // The die's side: `target` takes traffic leaving this die, `initiator`
  // delivers traffic arriving on it.
  tlm_utils::simple_target_socket<PassThroughLinkEndpoint> target{"target"};
  tlm_utils::simple_initiator_socket<PassThroughLinkEndpoint> initiator{"initiator"};
  // The side facing the other endpoint.
  tlm_utils::simple_initiator_socket<PassThroughLinkEndpoint> peer_initiator{"peer_initiator"};
  tlm_utils::simple_target_socket<PassThroughLinkEndpoint> peer_target{"peer_target"};

  explicit PassThroughLinkEndpoint(const sc_core::sc_module_name& name) : sc_module(name) {
    target.register_b_transport(this, &PassThroughLinkEndpoint::send);
    target.register_transport_dbg(this, &PassThroughLinkEndpoint::send_debug);
    target.register_get_direct_mem_ptr(this, &PassThroughLinkEndpoint::send_dmi_request);
    peer_initiator.register_invalidate_direct_mem_ptr(
        this, &PassThroughLinkEndpoint::return_dmi_invalidation);

    peer_target.register_b_transport(this, &PassThroughLinkEndpoint::deliver);
    peer_target.register_transport_dbg(this, &PassThroughLinkEndpoint::deliver_debug);
    peer_target.register_get_direct_mem_ptr(this, &PassThroughLinkEndpoint::deliver_dmi_request);
    initiator.register_invalidate_direct_mem_ptr(
        this, &PassThroughLinkEndpoint::send_dmi_invalidation);
  }

 private:
  // Leaving this die.
  void send(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    peer_initiator->b_transport(transaction, delay);
  }
  unsigned send_debug(tlm::tlm_generic_payload& transaction) {
    return peer_initiator->transport_dbg(transaction);
  }
  bool send_dmi_request(tlm::tlm_generic_payload& transaction, tlm::tlm_dmi& dmi) {
    return peer_initiator->get_direct_mem_ptr(transaction, dmi);
  }
  void send_dmi_invalidation(sc_dt::uint64 start, sc_dt::uint64 end) {
    peer_target->invalidate_direct_mem_ptr(start, end);
  }

  // Arriving on this die.
  void deliver(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    initiator->b_transport(transaction, delay);
  }
  unsigned deliver_debug(tlm::tlm_generic_payload& transaction) {
    return initiator->transport_dbg(transaction);
  }
  bool deliver_dmi_request(tlm::tlm_generic_payload& transaction, tlm::tlm_dmi& dmi) {
    return initiator->get_direct_mem_ptr(transaction, dmi);
  }
  void return_dmi_invalidation(sc_dt::uint64 start, sc_dt::uint64 end) {
    target->invalidate_direct_mem_ptr(start, end);
  }
};

}  // namespace socpuppet
