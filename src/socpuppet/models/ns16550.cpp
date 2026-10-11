#include "socpuppet/models/ns16550.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <memory>
#include <string>
#include <string_view>

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

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/borrowed_model.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

// The borrowed UART and what it needs around it. It sends each transmitted
// byte out of a socket as a one-byte write, and asks the same socket for
// each received byte. The far end of that socket is here. It is told
// through a second socket whether a byte is waiting to be asked for, which
// is all that socket carries. Its reset is never asserted, and its
// interrupt goes to a signal that nobody reads yet.
struct Ns16550::Model {
  Model() {
    uart_.sock_i_->bind(serial_line_);
    serial_line_.register_b_transport(this, &Model::OnTheSerialLine);
    byte_waiting_.bind(*uart_.sock_t_ext_);
    uart_.rst_in_.bind(reset_tied_low_);
    uart_.bindIRQ(0, &interrupt_unread_);
  }

  const std::string& Output() const { return output_; }

  // Takes bytes that have come in on the serial line. They wait here until
  // the firmware reads them.
  void Receive(std::string_view received) {
    received_.insert(received_.end(), received.begin(), received.end());
  }

  // Tells the borrowed model whether a received byte is waiting, which is
  // what its line status then says. Call it inside the simulation.
  void SayWhetherAByteIsWaiting() {
    // The borrowed model reads 32 bits, whatever it is sent, and looks at
    // the lowest.
    auto waiting =
        LittleEndianBytes(std::uint32_t{received_.empty() ? 0U : 1U});
    Transport(byte_waiting_, tlm::TLM_WRITE_COMMAND, 0, waiting);
  }

  // Passes on an access to register N, which is at offset N for us and at
  // 4 * N in the borrowed model.
  void AccessRegister(tlm::tlm_generic_payload& transaction,
                      sc_core::sc_time& delay) {
    const AtAddress in_the_model{transaction,
                                 transaction.get_address() * kRegisterSpacing};
    registers_.Access(transaction, delay);
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
    tlm::tlm_generic_payload look;
    SetUpAccess(look, tlm::TLM_READ_COMMAND,
                transaction.get_address() * kRegisterSpacing, whole);
    if (registers_.DebugAccess(look) != whole.size()) return 0;
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
      // read, into a byte it has not set. With none waiting the answer is
      // zero.
      std::uint8_t byte = 0;
      if (!received_.empty()) {
        byte = static_cast<std::uint8_t>(received_.front());
        received_.pop_front();
      }
      *transaction.get_data_ptr() = byte;
      // The model leaves its line status saying "data ready" until it is
      // told otherwise, so it is told again after each byte.
      SayWhetherAByteIsWaiting();
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }

  // The borrowed model spaces its registers four bytes apart.
  static constexpr std::size_t kRegisterSpacing = 4;
  static constexpr std::size_t kRegisters = 8;

  std::string output_;
  // What has come in on the serial line and has not been read yet.
  std::deque<char> received_;
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  sc_core::sc_signal<bool> interrupt_unread_{"interrupt_unread"};
  vpvper::pulpino::UART<Model> uart_{
      "uart",
      // base address, size in bytes, interrupts, registers
      scc::tlm_target_bfs_params{0, kRegisters * kRegisterSpacing, 1,
                                 kRegisters}};
  RegistersOf registers_{*uart_.sock_t_.get()};
  tlm_utils::simple_target_socket<Model> serial_line_{"serial_line"};
  tlm_utils::simple_initiator_socket<Model> byte_waiting_{"byte_waiting"};
};

Ns16550::Ns16550(const sc_core::sc_module_name& name)
    : sc_module(name), model_(std::make_unique<Model>()) {
  socket.register_b_transport(this, &Ns16550::b_transport);
  socket.register_transport_dbg(this, &Ns16550::transport_dbg);
  SC_METHOD(ShowWhatCameIn);
  sensitive << came_in_;
  dont_initialize();
}

Ns16550::~Ns16550() = default;

const std::string& Ns16550::Output() const { return model_->Output(); }

void Ns16550::Write(std::string_view received) {
  model_->Receive(received);
  // A delta cycle on, and in a process of the UART's own. Telling the
  // borrowed model may wake its interrupt process at once, which a model
  // may only do from inside the simulation, and whoever calls this may be
  // a script, between two runs of it.
  came_in_.notify(sc_core::SC_ZERO_TIME);
}

// A method, though it sends a transaction, which TLM keeps for threads: the
// target is the borrowed model inside this adapter, and it never waits.
void Ns16550::ShowWhatCameIn() { model_->SayWhetherAByteIsWaiting(); }

void Ns16550::b_transport(tlm::tlm_generic_payload& transaction,
                          sc_core::sc_time& delay) {
  model_->AccessRegister(transaction, delay);
}

unsigned Ns16550::transport_dbg(tlm::tlm_generic_payload& transaction) {
  return model_->LookAtRegister(transaction);
}

}  // namespace socpuppet
