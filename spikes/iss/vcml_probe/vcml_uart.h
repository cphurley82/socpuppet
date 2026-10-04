#ifndef SPIKES_ISS_VCML_PROBE_VCML_UART_H_
#define SPIKES_ISS_VCML_PROBE_VCML_UART_H_

#include <string>

#include <systemc>
#include <tlm>
#include <vcml/models/serial/uart.h>
// cpplint takes this for a C library header because of its name.
#include <vcml/protocols/serial.h>  // NOLINT(build/include_order)

namespace spike {

// VCML's 16550 UART, made to fit a socpuppet platform.
//
// The model is VCML's, untouched. What this adds is what any VCML model
// needs before it can stand among components that are not VCML's:
//   - a plain TLM socket, which VCML's own socket type can hand out;
//   - something on its clock and reset inputs, which every VCML peripheral
//     has, and on the ports we have no use for (interrupt, receive);
//   - somewhere for the transmitted bytes to go: here, a string.
// A VCML serial socket finds whoever receives its bytes by looking up the
// module hierarchy for a `serial_host`, which is why that base is public.
class VcmlUart : public sc_core::sc_module, public vcml::serial_host {
 private:
  // One byte per register, a 16-byte FIFO each way. Declared first because
  // `socket` below is made from it.
  vcml::serial::uart uart_{"uart", 1, 16, 16};

 public:
  // The UART's register socket, as the 32-bit TLM socket socpuppet binds.
  tlm::tlm_target_socket<>& socket;

  explicit VcmlUart(const sc_core::sc_module_name& name)
      : sc_module(name), socket(uart_.in.adapt<32>()) {
    uart_.serial_tx.bind(transmitted_);
    uart_.serial_rx.stub();
    uart_.irq.stub();
    uart_.clk.stub(10 * vcml::MHz);
    uart_.rst.stub();
  }

  // Everything transmitted so far.
  const std::string& Output() const { return output_; }

 private:
  void serial_receive(vcml::u8 data) override {
    output_ += static_cast<char>(data);
  }

  vcml::serial_target_socket transmitted_{"transmitted"};
  std::string output_;
};

}  // namespace spike

#endif  // SPIKES_ISS_VCML_PROBE_VCML_UART_H_
