#include "socpuppet/models/ns16550.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

#include <scc/tlm_target_bfs.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

// The borrowed header uses the two socket headers above without including
// them, so it has to come after them (see docs/upstream.md).
// clang-format off
#include <pulpino/uart.h>
// clang-format on

#include "socpuppet/platform/transport.h"

namespace socpuppet {

// The borrowed UART and what it needs around it. It sends each transmitted
// byte out of a socket as a one-byte write, and asks the same socket for
// each received byte. The far end of that socket is here. Its reset is
// never asserted, and its interrupt goes to a signal that nobody reads yet.
struct Ns16550::Model {
  Model() {
    to_registers_.bind(*uart_.sock_t_.get());
    uart_.sock_i_->bind(serial_line_);
    serial_line_.register_b_transport(this, &Model::OnTheSerialLine);
    nothing_received_.bind(*uart_.sock_t_ext_);
    uart_.rst_in_.bind(reset_tied_low_);
    uart_.bindIRQ(0, &interrupt_unread_);
  }

  const std::string& Output() const { return output_; }

  // Passes on an access to register N, which is at offset N for us and at
  // 4 * N in the borrowed model.
  void AccessRegister(tlm::tlm_generic_payload& transaction,
                      sc_core::sc_time& delay) {
    transaction.set_address(transaction.get_address() * kRegisterSpacing);
    to_registers_->b_transport(transaction, delay);
  }
  // A debugger's look at register N: one byte, in no simulated time.
  // Returns the bytes transferred. The borrowed model answers a debug
  // access only if it is as wide as its own registers, which are four bytes
  // each, so the whole register is fetched and its low byte handed back.
  // A debug write is declined: it would land in the borrowed register's
  // storage, where an ordinary read does not look (see docs/upstream.md).
  unsigned LookAtRegister(tlm::tlm_generic_payload& transaction) {
    if (!transaction.is_read() || transaction.get_data_length() != 1) return 0;
    std::array<std::uint8_t, kRegisterSpacing> whole{};
    if (DebugTransport(to_registers_, tlm::TLM_READ_COMMAND,
                       transaction.get_address() * kRegisterSpacing,
                       whole) != whole.size()) {
      return 0;
    }
    *transaction.get_data_ptr() = whole[0];
    return 1;
  }

 private:
  void OnTheSerialLine(tlm::tlm_generic_payload& transaction,
                       sc_core::sc_time&) {
    if (transaction.is_write()) {
      output_ += static_cast<char>(*transaction.get_data_ptr());
    } else {
      // The model asks for a received byte whenever its receive register is
      // read, into a byte it has not set. Nothing is ever received, so the
      // answer is zero.
      *transaction.get_data_ptr() = 0;
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }

  // The borrowed model spaces its registers four bytes apart.
  static constexpr std::size_t kRegisterSpacing = 4;
  static constexpr std::size_t kRegisters = 8;

  std::string output_;
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  sc_core::sc_signal<bool> interrupt_unread_{"interrupt_unread"};
  vpvper::pulpino::UART<Model> uart_{
      "uart",
      // base address, size in bytes, interrupts, registers
      scc::tlm_target_bfs_params{0, kRegisters * kRegisterSpacing, 1,
                                 kRegisters}};
  // The model's sockets have a bus width of zero, SCC's mark for "loosely
  // timed", and only bind to their like.
  tlm_utils::simple_initiator_socket<Model, scc::LT> to_registers_{
      "to_registers"};
  tlm_utils::simple_target_socket<Model> serial_line_{"serial_line"};
  tlm_utils::simple_initiator_socket<Model> nothing_received_{
      "nothing_received"};
};

Ns16550::Ns16550(const sc_core::sc_module_name& name)
    : sc_module(name), model_(std::make_unique<Model>()) {
  socket.register_b_transport(this, &Ns16550::b_transport);
  socket.register_transport_dbg(this, &Ns16550::transport_dbg);
}

Ns16550::~Ns16550() = default;

const std::string& Ns16550::Output() const { return model_->Output(); }

void Ns16550::b_transport(tlm::tlm_generic_payload& transaction,
                          sc_core::sc_time& delay) {
  model_->AccessRegister(transaction, delay);
}

unsigned Ns16550::transport_dbg(tlm::tlm_generic_payload& transaction) {
  return model_->LookAtRegister(transaction);
}

}  // namespace socpuppet
