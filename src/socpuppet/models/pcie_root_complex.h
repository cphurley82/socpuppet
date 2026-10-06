#ifndef SOCPUPPET_MODELS_PCIE_ROOT_COMPLEX_H_
#define SOCPUPPET_MODELS_PCIE_ROOT_COMPLEX_H_

#include <algorithm>
#include <cstdint>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/models/pcie_link.h"

namespace socpuppet {

// A PCIe root complex: where a host's memory-mapped bus meets a PCIe link.
//
//   host bus                                  the link
//   ecam ─────▶ configuration accesses ─┐
//   mmio ─────▶ memory accesses ────────┴──▶ to_device
//   dma  ◀───── the device's own accesses ◀── from_device
//
// The host reaches the device through two windows in its address map.
// `ecam` is the configuration window: 4 KiB of configuration space for
// each function, laid out by bus, device and function number. `mmio` is
// the memory window, in which the host places the device's registers.
// Whatever the device sends up the link (DMA, and interrupts as MSI-X
// messages) goes out of `dma`, onto the host's bus.
//
// One device is on the link, and it is function 0 of device 0 on bus 0.
// There are no bridges or switches, and no bus beyond the first.
class PcieRootComplex : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<PcieRootComplex> ecam{"ecam"};
  tlm_utils::simple_target_socket<PcieRootComplex> mmio{"mmio"};
  tlm_utils::simple_initiator_socket<PcieRootComplex> dma{"dma"};
  tlm_utils::simple_initiator_socket<PcieRootComplex> to_device{"to_device"};
  tlm_utils::simple_target_socket<PcieRootComplex> from_device{"from_device"};

  // `mmio_base` is where the memory window is on the host's bus. A bus
  // hands a target the offset of an access into its window, and the device
  // compares addresses on the host's bus, so the root complex has to know
  // what to add back.
  PcieRootComplex(const sc_core::sc_module_name& name, std::uint64_t mmio_base)
      : sc_module(name), mmio_base_(mmio_base) {
    ecam.register_b_transport(this, &PcieRootComplex::Configure);
    mmio.register_b_transport(this, &PcieRootComplex::AccessMemory);
    from_device.register_b_transport(this, &PcieRootComplex::PassUp);
  }

 private:
  // The configuration window gives each function 4 KiB.
  static constexpr std::uint64_t kFunctionConfigurationSize = 0x1000;

  void Configure(tlm::tlm_generic_payload& transaction,
                 sc_core::sc_time& delay) {
    const std::uint64_t function =
        transaction.get_address() / kFunctionConfigurationSize;
    if (function != 0) {
      // Nobody is there. A real bus answers a read of an empty slot with
      // all ones and lets a write fall on the floor, and that is how a
      // host finds out which slots are taken.
      if (transaction.is_read()) {
        std::fill_n(transaction.get_data_ptr(), transaction.get_data_length(),
                    0xFF);
      }
      transaction.set_response_status(tlm::TLM_OK_RESPONSE);
      return;
    }
    SendConfigurationAccess(
        to_device, transaction, delay,
        transaction.get_address() % kFunctionConfigurationSize);
  }

  void AccessMemory(tlm::tlm_generic_payload& transaction,
                    sc_core::sc_time& delay) {
    // The device compares addresses on the host's bus, and the bus handed
    // over an offset into the window.
    const std::uint64_t offset = transaction.get_address();
    transaction.set_address(mmio_base_ + offset);
    to_device->b_transport(transaction, delay);
    transaction.set_address(offset);
  }

  void PassUp(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    dma->b_transport(transaction, delay);
  }

  std::uint64_t mmio_base_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_PCIE_ROOT_COMPLEX_H_
