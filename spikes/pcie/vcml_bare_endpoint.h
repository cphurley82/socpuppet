#ifndef SPIKES_PCIE_VCML_BARE_ENDPOINT_H_
#define SPIKES_PCIE_VCML_BARE_ENDPOINT_H_

#include <cstdint>
#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "spikes/pcie/vcml_endpoint.h"

namespace spike {

// The same endpoint with only `vcml::pci::endpoint` borrowed, and no
// `vcml::pci::host`. The adapter plays the host's part towards VCML's PCI
// socket itself: it turns each transaction into one of VCML's PCI payloads,
// keeps track of where the BARs have been placed, and sends the endpoint's
// DMA and MSI-X messages out as plain transactions.
//
// This is the shape the real thing would have. socpuppet's root complex is
// its own component on the far side of a link made of plain TLM sockets, so
// VCML's host has no place to stand. `ecam` and `mmio` stand for the two
// kinds of access that would arrive over that link, and both take an
// address relative to the endpoint: a configuration register's offset, and
// a PCI bus address.
//
// It has the ports of VcmlEndpoint, so that the same tests run on both.
class VcmlBareEndpoint : public sc_core::sc_module {
 public:
  using Config = VcmlEndpoint::Config;

  tlm_utils::simple_target_socket<VcmlBareEndpoint> ecam{"ecam"};
  tlm_utils::simple_target_socket<VcmlBareEndpoint> mmio{"mmio"};
  tlm_utils::simple_initiator_socket<VcmlBareEndpoint> dma{"dma"};

  tlm::tlm_initiator_socket<> bar0{"bar0"};
  tlm::tlm_target_socket<> function_dma{"function_dma"};
  sc_core::sc_vector<sc_core::sc_in<bool>> irq;

  VcmlBareEndpoint(const sc_core::sc_module_name& name, const Config& config);
  ~VcmlBareEndpoint() override;

  void before_end_of_elaboration() override;
  void start_of_simulation() override;

 private:
  struct Model;

  void Configure(tlm::tlm_generic_payload& transaction, sc_core::sc_time&);
  unsigned DebugConfigure(tlm::tlm_generic_payload& transaction);
  void AccessMemory(tlm::tlm_generic_payload& transaction, sc_core::sc_time&);
  unsigned DebugAccessMemory(tlm::tlm_generic_payload& transaction);

  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  std::unique_ptr<Model> model_;
};

}  // namespace spike

#endif  // SPIKES_PCIE_VCML_BARE_ENDPOINT_H_
