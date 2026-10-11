#ifndef SOCPUPPET_MODELS_NS16550_H_
#define SOCPUPPET_MODELS_NS16550_H_

#include <memory>
#include <string>
#include <string_view>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// A 16550-style UART: the serial port a firmware's console prints through.
//
// The model is borrowed. It is the PULPino UART from VPV-Peripherals
// (VP-Vibes, written at the Technical University of Munich), and this class
// is the adapter that fits it into a socpuppet platform:
//   - Its registers are the 16550's eight, one byte each at offsets 0 to 7,
//     as on the original chip. (The borrowed model spaces them four bytes
//     apart. The adapter does the arithmetic.)
//   - What the firmware transmits is kept, to be read with Output(), and
//     what it is to receive is handed over with Write(). Whoever holds
//     the UART is the other end of its serial line.
class Ns16550 : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Ns16550> socket{"socket"};
  // The interrupt, for an interrupt controller's input: high while an
  // interrupt the firmware enabled is pending. That is while a received
  // byte waits. And it is from when the transmit register empties, which
  // here is as soon as it is written, or from when that interrupt is
  // enabled, until firmware asks which interrupt it is.
  sc_core::sc_out<bool> irq{"irq"};

  explicit Ns16550(const sc_core::sc_module_name& name);
  ~Ns16550() override;

  // Everything transmitted so far.
  const std::string& Output() const;

  // Bytes that come in on the serial line, as if typed at the other end.
  // Firmware reads them from the receive register, in order. They show in
  // the registers a delta cycle later, and all at once: there is no baud
  // rate to pace them, and no overrun, since they wait here until read.
  void Write(std::string_view received);

 private:
  struct Model;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay);
  // Debug transport: a register as a debugger sees it, in no simulated
  // time. Returns the bytes transferred.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction);
  // Has the registers show that bytes have come in.
  void ShowWhatCameIn();

  std::unique_ptr<Model> model_;
  sc_core::sc_event came_in_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_NS16550_H_
