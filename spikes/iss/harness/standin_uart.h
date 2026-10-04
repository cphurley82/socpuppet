#ifndef SPIKES_ISS_HARNESS_STANDIN_UART_H_
#define SPIKES_ISS_HARNESS_STANDIN_UART_H_

#include <array>
#include <cstdint>
#include <string>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace spike {

// A stand-in for an NS16550 UART, with just enough behind it for a polled
// console driver to print: the transmitter always says it is ready, and
// every byte written to it is kept for the test to read.
//
// It never receives, never interrupts, and takes no time. An access names
// the register at its address, and only its first byte counts, whatever
// its length.
class StandinUart : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<StandinUart> socket{"socket"};

  explicit StandinUart(const sc_core::sc_module_name& name) : sc_module(name) {
    socket.register_b_transport(this, &StandinUart::b_transport);
  }

  // Everything transmitted so far.
  const std::string& Output() const { return output_; }

 private:
  static constexpr std::uint64_t kTransmitHolding = 0;
  static constexpr std::uint64_t kLineControl = 3;
  static constexpr std::uint64_t kLineStatus = 5;
  // In the line control register: offsets 0 and 1 are the baud rate
  // divisor, not the data registers.
  static constexpr std::uint8_t kDivisorLatchAccess = 0x80;
  // In the line status register: the transmitter can take a byte, and has
  // nothing left to send.
  static constexpr std::uint8_t kTransmitterReady = 0x60;

  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const std::uint64_t offset = transaction.get_address();
    if (offset >= registers_.size() || transaction.get_data_length() == 0) {
      transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
      return;
    }
    std::uint8_t& byte = *transaction.get_data_ptr();
    if (transaction.is_read()) {
      byte = offset == kLineStatus ? kTransmitterReady : registers_[offset];
    } else if (offset == kTransmitHolding &&
               (registers_[kLineControl] & kDivisorLatchAccess) == 0) {
      output_ += static_cast<char>(byte);
    } else {
      registers_[offset] = byte;
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }

  std::array<std::uint8_t, 8> registers_{};
  std::string output_;
};

}  // namespace spike

#endif  // SPIKES_ISS_HARNESS_STANDIN_UART_H_
