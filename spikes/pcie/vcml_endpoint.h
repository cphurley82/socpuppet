#ifndef SPIKES_PCIE_VCML_ENDPOINT_H_
#define SPIKES_PCIE_VCML_ENDPOINT_H_

#include <cstddef>
#include <cstdint>
#include <memory>

#include <systemc>
#include <tlm>

namespace spike {

// A PCIe endpoint with its side of the root complex, both borrowed from VCML
// (MachineWare): `vcml::pci::host` wired to a `vcml::pci::endpoint`. The two
// talk to each other over VCML's own PCI sockets, which nothing outside can
// bind, trace or carry across a link. So they live together in here, and
// only plain TLM sockets and wires come out.
//
//   ecam  ─▶ ┌──────────────────────────────┐ ─▶ bar0          (the
//   mmio  ─▶ │ pci::host ══ pci::endpoint   │ ◀─ function_dma   function's
//   dma   ◀─ └──────────────────────────────┘ ◀─ irq[N]         side)
//
// The endpoint owns configuration space, one 64-bit memory BAR and the
// MSI-X capability with its table. The function behind it is somebody
// else's: a register block on `bar0`, DMA into `function_dma`, and one
// interrupt line per MSI-X vector.
class VcmlEndpoint : public sc_core::sc_module {
 public:
  struct Config {
    std::uint16_t vendor_id = 0;
    std::uint16_t device_id = 0;
    // Base class, subclass and programming interface, as configuration
    // space has them: 0x010802 is an NVMe controller.
    std::uint32_t class_code = 0;
    // How much of BAR0 is the function's. The MSI-X table and its pending
    // bits follow, and the BAR is as large as the next power of two.
    std::uint64_t function_size = 0;
    std::size_t vectors = 1;
    // Whether VCML may ask the far end of `dma` for direct memory access
    // (DMI) and then write there without a transaction.
    bool dma_by_dmi = false;
  };

  // The host's side. Configuration accesses arrive on `ecam` at ECAM
  // offsets (bus << 20 | device << 15 | function << 12 | register), and the
  // endpoint is function 00:00.0. Memory accesses arrive on `mmio` at PCI
  // bus addresses, the ones the BARs are programmed with. `dma` carries
  // the function's DMA and the MSI-X messages towards the host's memory.
  tlm::tlm_target_socket<> ecam{"ecam"};
  tlm::tlm_target_socket<> mmio{"mmio"};
  tlm::tlm_initiator_socket<> dma{"dma"};

  // The function's side.
  tlm::tlm_initiator_socket<> bar0{"bar0"};
  tlm::tlm_target_socket<> function_dma{"function_dma"};
  sc_core::sc_vector<sc_core::sc_in<bool>> irq;

  VcmlEndpoint(const sc_core::sc_module_name& name, const Config& config);
  ~VcmlEndpoint() override;

  // SystemC's last chance to bind a port: an interrupt line nobody
  // connected is tied low.
  void before_end_of_elaboration() override;
  void start_of_simulation() override;

 private:
  struct Model;

  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  std::unique_ptr<Model> model_;
};

}  // namespace spike

#endif  // SPIKES_PCIE_VCML_ENDPOINT_H_
