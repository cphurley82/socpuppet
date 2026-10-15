#ifndef SOCPUPPET_MODELS_APLIC_H_
#define SOCPUPPET_MODELS_APLIC_H_

#include <cstddef>
#include <cstdint>
#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// The RISC-V advanced platform-level interrupt controller (APLIC), as it
// is on a platform whose hart is sent its interrupts as messages: the
// interrupt lines of devices that only have a wire come in, and for each
// interrupt a write goes out, to the page of the hart's IMSIC. The APLIC
// can so sit with its devices, on another die than the hart, with nothing
// but a bus between them.
//
// Firmware says where the messages go and, for each source, which
// interrupt identity to send. It switches a source on by giving it a mode
// and enabling it. Where firmware never says where messages go, as
// OpenSBI and Linux do not for an APLIC that serves supervisor mode alone,
// `messages_to` is the address of the page to send them to until it does,
// as the registers that say so read. Zero is nowhere: firmware will say.
//
// The model is borrowed: the APLIC from VPV-Peripherals (Qualcomm's),
// with delivery by message added to it. This class is the adapter that
// fits it into a socpuppet platform.
class Aplic : public sc_core::sc_module {
 public:
  // Sources are numbered from 1, as the APLIC numbers them: 0 means "none".
  static constexpr std::size_t kSources = 31;

  tlm_utils::simple_target_socket<Aplic> socket{"socket"};
  // The devices' interrupt lines. Source N is sources[N - 1]. One left
  // unconnected is tied low.
  sc_core::sc_vector<sc_core::sc_in<bool>> sources{"source", kSources};
  // Where the messages go out: 32-bit writes of an interrupt identity, at
  // the address firmware gave for the hart's page.
  tlm_utils::simple_initiator_socket<Aplic> msi{"msi"};

  explicit Aplic(const sc_core::sc_module_name& name,
                 std::uint64_t messages_to = 0);
  ~Aplic() override;

  // SystemC's last chance to bind a port. By now we know which sources
  // anyone connected.
  void before_end_of_elaboration() override;

 private:
  struct Model;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay);
  void WriteTheDomainConfiguration(tlm::tlm_generic_payload& transaction,
                                   sc_core::sc_time& delay);

  // What a source left unconnected is bound to.
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  std::unique_ptr<Model> model_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_APLIC_H_
