#ifndef SOCPUPPET_MODELS_PASS_THROUGH_LINK_H_
#define SOCPUPPET_MODELS_PASS_THROUGH_LINK_H_

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
  tlm_utils::simple_initiator_socket<PassThroughLinkEndpoint> initiator{
      "initiator"};
  // The side facing the other endpoint.
  tlm_utils::simple_initiator_socket<PassThroughLinkEndpoint> peer_initiator{
      "peer_initiator"};
  tlm_utils::simple_target_socket<PassThroughLinkEndpoint> peer_target{
      "peer_target"};

  explicit PassThroughLinkEndpoint(const sc_core::sc_module_name& name)
      : sc_module(name) {
    target.register_b_transport(this, &PassThroughLinkEndpoint::Send);
    target.register_transport_dbg(this, &PassThroughLinkEndpoint::SendDebug);
    target.register_get_direct_mem_ptr(
        this, &PassThroughLinkEndpoint::SendDmiRequest);
    peer_initiator.register_invalidate_direct_mem_ptr(
        this, &PassThroughLinkEndpoint::PassInvalidationToDie);

    peer_target.register_b_transport(this, &PassThroughLinkEndpoint::Deliver);
    peer_target.register_transport_dbg(this,
                                       &PassThroughLinkEndpoint::DeliverDebug);
    peer_target.register_get_direct_mem_ptr(
        this, &PassThroughLinkEndpoint::DeliverDmiRequest);
    initiator.register_invalidate_direct_mem_ptr(
        this, &PassThroughLinkEndpoint::PassInvalidationToPeer);
  }

 private:
  // Leaving this die.
  void Send(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    peer_initiator->b_transport(transaction, delay);
  }
  unsigned SendDebug(tlm::tlm_generic_payload& transaction) {
    return peer_initiator->transport_dbg(transaction);
  }
  bool SendDmiRequest(tlm::tlm_generic_payload& transaction,
                      tlm::tlm_dmi& dmi) {
    return peer_initiator->get_direct_mem_ptr(transaction, dmi);
  }
  void PassInvalidationToPeer(sc_dt::uint64 start, sc_dt::uint64 end) {
    peer_target->invalidate_direct_mem_ptr(start, end);
  }

  // Arriving on this die.
  void Deliver(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    initiator->b_transport(transaction, delay);
  }
  unsigned DeliverDebug(tlm::tlm_generic_payload& transaction) {
    return initiator->transport_dbg(transaction);
  }
  bool DeliverDmiRequest(tlm::tlm_generic_payload& transaction,
                         tlm::tlm_dmi& dmi) {
    return initiator->get_direct_mem_ptr(transaction, dmi);
  }
  void PassInvalidationToDie(sc_dt::uint64 start, sc_dt::uint64 end) {
    target->invalidate_direct_mem_ptr(start, end);
  }
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_PASS_THROUGH_LINK_H_
