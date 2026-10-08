#ifndef SOCPUPPET_MODELS_MSI_RECEIVER_H_
#define SOCPUPPET_MODELS_MSI_RECEIVER_H_

#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

// Stand-in for the part of a host's interrupt controller that takes
// message-signalled interrupts (MSI).
//
// A PCIe device has no interrupt wire to the host. It interrupts by
// writing a small message to an address the host chose, and something at
// that address has to turn the write back into an interrupt for the CPU.
// On a RISC-V host that is an IMSIC, and on a PC the local APIC.
//
// This stand-in is one 32-bit register and one wire.
//   - A write is a message, and its data is the number of a vector, 0 to
//     31. The vector is then waiting, and the wire is high while any is.
//   - A read returns the vectors that are waiting, one bit each, and none
//     of them is waiting afterwards.
// A host therefore has every message sent to this register's address, with
// the vector's own number as its data.
class MsiReceiver : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<MsiReceiver> socket{"socket"};
  sc_core::sc_out<bool> irq{"irq"};

  explicit MsiReceiver(const sc_core::sc_module_name& name) : sc_module(name) {
    socket.register_b_transport(this, &MsiReceiver::b_transport);
    socket.register_transport_dbg(this, &MsiReceiver::transport_dbg);
    SC_METHOD(DriveTheLine);
    sensitive << changed_;
    dont_initialize();
  }

 private:
  static constexpr std::uint32_t kVectors = 32;

  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    if (transaction.get_address() != 0 ||
        transaction.get_data_length() != sizeof waiting_) {
      transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
      return;
    }
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    if (transaction.is_read()) {
      StoreLittleEndian(waiting_, data);
      waiting_ = 0;
    } else {
      const auto value = LoadLittleEndian<std::uint32_t>(data);
      if (value >= kVectors) {
        transaction.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
        return;
      }
      waiting_ |= std::uint32_t{1} << value;
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
    changed_.notify();
  }

  // Debug transport: a debugger looking at which vectors are waiting, which
  // leaves them waiting. A debug write is declined: a message is a bus
  // access, not a register a debugger pokes. Returns the bytes transferred.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    if (!transaction.is_read()) return 0;
    if (transaction.get_address() != 0 ||
        transaction.get_data_length() != sizeof waiting_) {
      return 0;
    }
    StoreLittleEndian(
        waiting_, {transaction.get_data_ptr(), transaction.get_data_length()});
    return sizeof waiting_;
  }

  // The only process that writes the line. A message arrives in the
  // device's process and a read in the host's, and a SystemC signal takes
  // one writer in a delta cycle.
  void DriveTheLine() { irq.write(waiting_ != 0); }

  // Which vectors have had a message since the host last read: one bit
  // each.
  std::uint32_t waiting_ = 0;
  sc_core::sc_event changed_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_MSI_RECEIVER_H_
