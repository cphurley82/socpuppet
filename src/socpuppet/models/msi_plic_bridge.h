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
    SC_METHOD(DriveTheLines);
    sensitive << changed_;
    dont_initialize();
  }

 private:
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    if (transaction.is_read()) {
      std::fill_n(transaction.get_data_ptr(), transaction.get_data_length(),
                  static_cast<unsigned char>(0));
    }
    const auto vector = LoadLittleEndian<std::uint32_t>(
        {transaction.get_data_ptr(), transaction.get_data_length()});
    if (vector >= waiting_.size()) {
      transaction.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
      return;
    }
    ++waiting_[vector];
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
    changed_.notify(sc_core::SC_ZERO_TIME);
  }

  // The only process that writes the lines. A message arrives in the
  // sending device's process, and a SystemC signal takes one writer.
  //
  // Each message gets a rise of its own, and a rise needs a fall before
  // it. So a line that is high falls, and only a line that is low rises
  // for the next message waiting.
  void DriveTheLines() {
    bool more_to_do = false;
    for (std::size_t vector = 0; vector < irq.size(); ++vector) {
      const bool rise = !irq[vector].read() && waiting_[vector] > 0;
      if (rise) --waiting_[vector];
      irq[vector].write(rise);
      // What rose now falls a delta cycle on, and what fell may have
      // another message to rise for.
      more_to_do = more_to_do || rise || waiting_[vector] > 0;
    }
    if (more_to_do) changed_.notify(sc_core::SC_ZERO_TIME);
  }

  // How many messages each vector has had that are not yet on its line.
  std::vector<std::uint32_t> waiting_;
  sc_core::sc_event changed_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_MSI_PLIC_BRIDGE_H_
