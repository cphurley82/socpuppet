#ifndef SOCPUPPET_MODELS_NS16550_H_
#define SOCPUPPET_MODELS_NS16550_H_

#include <memory>
#include <string>

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
//   - What the firmware transmits is kept, to be read with Output().
// Nothing is ever received, and the interrupt is not connected yet.
class Ns16550 : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Ns16550> socket{"socket"};

  explicit Ns16550(const sc_core::sc_module_name& name);
  ~Ns16550() override;

  // Everything transmitted so far.
  const std::string& Output() const;

 private:
  struct Model;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay);

  std::unique_ptr<Model> model_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_NS16550_H_
