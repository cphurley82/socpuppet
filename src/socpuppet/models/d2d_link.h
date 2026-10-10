#ifndef SOCPUPPET_MODELS_D2D_LINK_H_
#define SOCPUPPET_MODELS_D2D_LINK_H_

#include <cstdint>
#include <optional>
#include <span>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/d2d_link_logic.h"
#include "socpuppet/core/time.h"
#include "socpuppet/core/ucie_sideband.h"
#include "socpuppet/platform/time_conversion.h"

namespace socpuppet {

// One end of the die-to-die link, in the style of UCIe. A link is two of
// these, one on each die, with their peer sockets bound to each other.
//
// There are two paths between the dies, as there are on real hardware.
// The mainband is the wide one that carries the dies' traffic, and it
// carries nothing until the link has been trained. The sideband is the
// narrow management one, which is up from the start: it is how the two
// ends agree to bring the mainband up, and how the firmware on one die
// reaches the other's registers.
//
//   this die                                    the other die
//   target ──────────▶ peer_initiator ════▶ peer_target ──────▶ initiator
//   initiator ◀─────── peer_target    ◀════ peer_initiator ◀─── target
//   sideband ─▶ its registers ─▶ sideband_peer_initiator ═══▶ ...
//   reset ───▶ this die's CPU, held until the other die lets it go
//   irq ─────▶ this die's interrupt controller
//
// This link never grants direct memory access: every access has to cross
// it and be seen taking its time, which is what the model is for.
//
// What happens when is D2dLinkLogic's; this is the shell around it: the
// sockets, the wires and the waiting.
class D2dLinkEndpoint : public sc_core::sc_module {
 public:
  // The die's side of the mainband: `target` takes traffic leaving this
  // die, `initiator` delivers traffic arriving on it.
  tlm_utils::simple_target_socket<D2dLinkEndpoint> target{"target"};
  tlm_utils::simple_initiator_socket<D2dLinkEndpoint> initiator{"initiator"};
  // The mainband side facing the other end.
  tlm_utils::simple_initiator_socket<D2dLinkEndpoint> peer_initiator{
      "peer_initiator"};
  tlm_utils::simple_target_socket<D2dLinkEndpoint> peer_target{"peer_target"};

  // The link's own registers, as this die's firmware reaches them.
  tlm_utils::simple_target_socket<D2dLinkEndpoint> sideband{"sideband"};
  // The sideband between the two ends. A packet travels as one write of
  // its bytes at address zero, so that a trace of this pair reads as a
  // capture of the sideband.
  tlm_utils::simple_initiator_socket<D2dLinkEndpoint> sideband_peer_initiator{
      "sideband_peer_initiator"};
  tlm_utils::simple_target_socket<D2dLinkEndpoint> sideband_peer_target{
      "sideband_peer_target"};

  // High while this die is held in reset, and while the link has
  // something to tell this die's firmware that it asked to be told.
  sc_core::sc_out<bool> reset{"reset"};
  sc_core::sc_out<bool> irq{"irq"};

  D2dLinkEndpoint(const sc_core::sc_module_name& name, Picoseconds latency,
                  std::uint64_t bytes_per_ns, Picoseconds training)
      : sc_module(name), logic_(latency, bytes_per_ns, training) {
    target.register_b_transport(this, &D2dLinkEndpoint::Send);
    target.register_transport_dbg(this, &D2dLinkEndpoint::SendDebug);
    peer_target.register_b_transport(this, &D2dLinkEndpoint::Deliver);
    peer_target.register_transport_dbg(this, &D2dLinkEndpoint::DeliverDebug);
    sideband.register_b_transport(this, &D2dLinkEndpoint::AccessRegister);
    sideband_peer_target.register_b_transport(this,
                                              &D2dLinkEndpoint::TakePacket);
    // The one process there is, so it is the one that writes the wires,
    // which a SystemC signal takes only one writer of. It runs once
    // before any time has passed, so the reset this end holds is high
    // from the first delta cycle, before the die's CPU has looked at it.
    SC_THREAD(Work);
  }

 private:
  static Picoseconds Now() { return ToPicoseconds(sc_core::sc_time_stamp()); }

  // Leaving this die, on the mainband. A link that is not up carries
  // nothing: the access is refused where it stands, as a bus fault to the
  // firmware that made it.
  void Send(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    if (!logic_.IsActive()) {
      transaction.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
      return;
    }
    const Picoseconds departure =
        ToPicoseconds(sc_core::sc_time_stamp() + delay);
    const Picoseconds arrival =
        logic_.Cross(transaction.get_data_length(), departure);
    delay = ToScTime(arrival) - sc_core::sc_time_stamp();
    peer_initiator->b_transport(transaction, delay);
  }

  // A debugger's look crosses whatever the link's state: it is not
  // traffic, and what it sees is what the other die holds.
  unsigned SendDebug(tlm::tlm_generic_payload& transaction) {
    return peer_initiator->transport_dbg(transaction);
  }

  // Arriving on this die: its time was counted where it set off.
  void Deliver(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    initiator->b_transport(transaction, delay);
  }
  unsigned DeliverDebug(tlm::tlm_generic_payload& transaction) {
    return initiator->transport_dbg(transaction);
  }

  // This die's firmware reading and writing the link's registers.
  void AccessRegister(tlm::tlm_generic_payload& transaction,
                      sc_core::sc_time&) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    const bool ok = transaction.is_read()
                        ? logic_.ReadRegister(transaction.get_address(), data)
                        : logic_.WriteRegister(transaction.get_address(), data);
    transaction.set_response_status(ok ? tlm::TLM_OK_RESPONSE
                                       : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    if (transaction.is_write()) work_.notify(sc_core::SC_ZERO_TIME);
  }

  // A sideband packet from the other end.
  void TakePacket(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const std::span<const std::uint8_t> bytes{transaction.get_data_ptr(),
                                              transaction.get_data_length()};
    const std::optional<SidebandPacket> packet = SidebandPacket::Decode(bytes);
    transaction.set_response_status(packet ? tlm::TLM_OK_RESPONSE
                                           : tlm::TLM_GENERIC_ERROR_RESPONSE);
    if (!packet) return;
    logic_.Receive(*packet, Now());
    work_.notify(sc_core::SC_ZERO_TIME);
  }

  void Work() {
    for (;;) {
      const std::optional<Picoseconds> next = logic_.Advance(Now());
      DriveTheLines();
      SendWhatTheLinkHasToSay();
      if (next) {
        wait(ToScTime(*next) - sc_core::sc_time_stamp(), work_);
      } else {
        wait(work_);
      }
    }
  }

  // Puts each packet on the sideband as a write of its bytes. Nothing
  // waits for a reply: an answer comes back as a packet of its own.
  void SendWhatTheLinkHasToSay() {
    for (const SidebandPacket& packet : logic_.TakeOutgoing()) {
      std::vector<std::uint8_t> bytes = packet.Encode();
      tlm::tlm_generic_payload transaction;
      transaction.set_command(tlm::TLM_WRITE_COMMAND);
      transaction.set_address(0);
      transaction.set_data_ptr(bytes.data());
      transaction.set_data_length(static_cast<unsigned>(bytes.size()));
      transaction.set_streaming_width(static_cast<unsigned>(bytes.size()));
      transaction.set_response_status(tlm::TLM_INCOMPLETE_RESPONSE);
      sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
      sideband_peer_initiator->b_transport(transaction, delay);
    }
  }

  void DriveTheLines() {
    reset.write(logic_.ResetAsserted());
    irq.write(logic_.Interrupting());
  }

  D2dLinkLogic logic_;
  // Notified when the link may have something to do: firmware has written
  // a register, or a packet has arrived.
  sc_core::sc_event work_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_D2D_LINK_H_
