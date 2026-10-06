#ifndef SPIKES_PCIE_VCML_PARTS_H_
#define SPIKES_PCIE_VCML_PARTS_H_

// What the spike's two adapters share. It includes VCML's headers, so only
// the adapters' own source files may include it.

#include <cstddef>
#include <cstdint>

#include <systemc>
#include <tlm>
#include <vcml/core/systemc.h>
#include <vcml/models/pci/endpoint.h>

#include "spikes/pcie/vcml_endpoint.h"

namespace spike {

// VCML's MSI-X table entry is 16 bytes, and the pending bits come in
// 32-bit words.
constexpr std::uint64_t kTableEntrySize = 16;

inline std::uint64_t MsixSize(std::size_t vectors) {
  return (vectors * kTableEntrySize) + (((vectors + 31) / 32) * 4);
}

inline vcml::pci_config PciConfig(const VcmlEndpoint::Config& config) {
  return {.pcie = true,
          .vendor_id = config.vendor_id,
          .device_id = config.device_id,
          .subvendor_id = 0xFFFF,
          .subsystem_id = 0xFFFF,
          .class_code = vcml::pci_class_code(config.class_code, 0),
          .latency_timer = 0,
          .max_latency = 0,
          .min_grant = 0,
          // No legacy interrupt pin: with MSI-X off, the lines go nowhere.
          .int_pin = vcml::PCI_IRQ_NONE};
}

// VCML's endpoint, with three things put right for us: its power-on reset,
// its MSI-X table, and its answer to a debug access. (Building with
// SPIKE_VCML_AS_IS leaves them as they come, for as_is_test.cpp.)
class CorrectedEndpoint : public vcml::pci::endpoint {
 public:
  using endpoint::endpoint;

#ifndef SPIKE_VCML_AS_IS
  // The power-on reset. VCML's models are reset by a pulse on their reset
  // line, which here never comes, and until then BAR0 does not say that it
  // is a 64-bit BAR.
  void end_of_elaboration() override {
    endpoint::end_of_elaboration();
    reset();
  }

 protected:
  // pci::endpoint sends every access to a BAR out of `bar_out`, including
  // the ones meant for the MSI-X table that pci::device keeps inside that
  // same BAR, so the table could never be programmed. Here those go to the
  // table.
  unsigned int receive(vcml::tlm_generic_payload& transaction,
                       const vcml::tlm_sbi& sideband,
                       vcml::address_space space) override {
    const vcml::range address{transaction};
    if (m_msix != nullptr &&
        ((space == m_msix->tbl_as && address.overlaps(m_msix->tbl)) ||
         (space == m_msix->pba_as && address.overlaps(m_msix->pba)))) {
      return device::receive(transaction, sideband, space);
    }
    const unsigned int bytes = endpoint::receive(transaction, sideband, space);
    // A target is free to leave a debug access unanswered, response status
    // and all, and ours do. VCML stops the process over a transaction that
    // comes back without one.
    if (sideband.is_debug &&
        transaction.get_response_status() == tlm::TLM_INCOMPLETE_RESPONSE) {
      transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
    }
    return bytes;
  }
#endif
};

}  // namespace spike

#endif  // SPIKES_PCIE_VCML_PARTS_H_
