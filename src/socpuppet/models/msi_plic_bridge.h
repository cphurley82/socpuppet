#ifndef SOCPUPPET_MODELS_MSI_PLIC_BRIDGE_H_
#define SOCPUPPET_MODELS_MSI_PLIC_BRIDGE_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

// Turns message-signalled interrupts (MSI) into interrupt lines, one for
// each vector, for the sources of an interrupt controller that only has
// lines: a PLIC.
//
// A PCIe device has no interrupt wire to the host. It interrupts by
// writing a small message to an address the host chose. A RISC-V host
// with an IMSIC takes such a message as it is. One with only a PLIC needs
// something at that address to turn the write back into a wire, and this
// is that something.
//
// It is one 32-bit register, which reads as zero. A write is a message,
// and its data is the number of a vector, counted from 0. That vector's
// line rises, and falls again a delta cycle later. (A delta cycle is one round
// of the simulator letting every process that is ready run, with no time
// passing.)
//
// The line cannot stay high until the interrupt is handled, because
// nothing tells the bridge that it was: the handler talks to the device
// and to the PLIC. So the bridge only passes the edge on, and it is the
// PLIC that remembers.
class MsiPlicBridge : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<MsiPlicBridge> socket{"socket"};
  // One line for each vector.
  sc_core::sc_vector<sc_core::sc_out<bool>> irq;

  MsiPlicBridge(const sc_core::sc_module_name& name, std::size_t vectors)
      : sc_module(name), irq("irq", vectors), waiting_(vectors) {
    socket.register_b_transport(this, &MsiPlicBridge::b_transport);
    socket.register_transport_dbg(this, &MsiPlicBridge::transport_dbg);
    SC_METHOD(DriveTheLines);
    sensitive << changed_;
    dont_initialize();
  }

 private:
  static constexpr unsigned kRegisterSize = 4;

  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    if (transaction.get_address() != 0 ||
        transaction.get_data_length() != kRegisterSize) {
      transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
      return;
    }
    if (transaction.is_read()) {
      std::fill_n(transaction.get_data_ptr(), transaction.get_data_length(),
                  static_cast<unsigned char>(0));
      transaction.set_response_status(tlm::TLM_OK_RESPONSE);
      return;
    }
    const auto vector = LoadLittleEndian<std::uint32_t>(
        {transaction.get_data_ptr(), transaction.get_data_length()});
    if (vector >= waiting_.size()) {
      transaction.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
      return;
    }
    waiting_[vector] = true;
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
    // In the next delta cycle and not in this one: DriveTheLines reads its
    // own lines, and a line shows what was written to it a delta cycle
    // later. Run twice in one, it would raise a line it had just lowered,
    // and the fall would never be seen.
    changed_.notify(sc_core::SC_ZERO_TIME);
  }

  // Debug transport: a debugger looking at the register, which reads as
  // zero for it too. A debug write is declined: a message is a bus access
  // by a device, not a register a debugger pokes. Returns the bytes
  // transferred.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    if (!transaction.is_read()) return 0;
    std::fill_n(transaction.get_data_ptr(), transaction.get_data_length(),
                static_cast<unsigned char>(0));
    return transaction.get_data_length();
  }

  // The only process that writes the lines. A message arrives in the
  // sending device's process, and a SystemC signal takes one writer.
  //
  // A message needs a rise that comes after it, and a rise needs a fall
  // before it. So a line that is high falls, and only a line that is low
  // rises for a message that is waiting.
  void DriveTheLines() {
    bool more_to_do = false;
    for (std::size_t vector = 0; vector < irq.size(); ++vector) {
      const bool rise = !irq[vector].read() && waiting_[vector];
      if (rise) waiting_[vector] = false;
      irq[vector].write(rise);
      // What rose now falls a delta cycle on, and what fell may have a
      // message to rise for.
      more_to_do = more_to_do || rise || waiting_[vector];
    }
    if (more_to_do) changed_.notify(sc_core::SC_ZERO_TIME);
  }

  // Which vectors have had a message that is not yet on its line. It is a
  // flag and not a count, as the pending bit of a vector is: messages that
  // arrive before the line can rise are one interrupt.
  std::vector<bool> waiting_;
  sc_core::sc_event changed_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_MSI_PLIC_BRIDGE_H_
