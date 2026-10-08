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
    ecam.register_transport_dbg(this, &PcieRootComplex::ConfigureDebug);
    mmio.register_b_transport(this, &PcieRootComplex::AccessMemory);
    mmio.register_transport_dbg(this, &PcieRootComplex::AccessMemoryDebug);
    from_device.register_b_transport(this, &PcieRootComplex::PassUp);
    from_device.register_transport_dbg(this, &PcieRootComplex::PassUpDebug);
  }

 private:
  // The configuration window gives each function 4 KiB.
  static constexpr std::uint64_t kFunctionConfigurationSize = 0x1000;

  // Which function a configuration access is for, or nobody, and which of
  // its registers.
  static std::uint64_t FunctionOf(const tlm::tlm_generic_payload& transaction) {
    return transaction.get_address() / kFunctionConfigurationSize;
  }
  static std::uint64_t OffsetOf(const tlm::tlm_generic_payload& transaction) {
    return transaction.get_address() % kFunctionConfigurationSize;
  }

  // Nobody is there. A real bus answers a read of an empty slot with all
  // ones and lets a write fall on the floor, and that is how a host finds
  // out which slots are taken.
  static void AnswerForAnEmptySlot(tlm::tlm_generic_payload& transaction) {
    if (transaction.is_read()) {
      std::fill_n(transaction.get_data_ptr(), transaction.get_data_length(),
                  0xFF);
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }

  void Configure(tlm::tlm_generic_payload& transaction,
                 sc_core::sc_time& delay) {
    if (FunctionOf(transaction) != 0) {
      AnswerForAnEmptySlot(transaction);
      return;
    }
    AsConfigurationAccess access{transaction, OffsetOf(transaction)};
    to_device->b_transport(transaction, delay);
  }

  // Debug transport: the same, in no simulated time and with no side
  // effects, the way a debugger looks. Returns the bytes transferred.
  unsigned ConfigureDebug(tlm::tlm_generic_payload& transaction) {
    if (FunctionOf(transaction) != 0) {
      AnswerForAnEmptySlot(transaction);
      return transaction.get_data_length();
    }
    AsConfigurationAccess access{transaction, OffsetOf(transaction)};
    return to_device->transport_dbg(transaction);
  }

  void AccessMemory(tlm::tlm_generic_payload& transaction,
                    sc_core::sc_time& delay) {
    // The device compares addresses on the host's bus, and the bus handed
    // over an offset into the window.
    const AtAddress on_the_hosts_bus{transaction,
                                     mmio_base_ + transaction.get_address()};
    to_device->b_transport(transaction, delay);
  }

  unsigned AccessMemoryDebug(tlm::tlm_generic_payload& transaction) {
    const AtAddress on_the_hosts_bus{transaction,
                                     mmio_base_ + transaction.get_address()};
    return to_device->transport_dbg(transaction);
  }

  void PassUp(tlm::tlm_generic_payload& transaction, sc_core::sc_time& delay) {
    dma->b_transport(transaction, delay);
  }

  unsigned PassUpDebug(tlm::tlm_generic_payload& transaction) {
    return dma->transport_dbg(transaction);
  }

  std::uint64_t mmio_base_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_PCIE_ROOT_COMPLEX_H_
