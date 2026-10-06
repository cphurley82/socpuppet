#include "spikes/pcie/vcml_endpoint.h"

#include <bit>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

// cpplint takes some of VCML's directories for the C library's.
#include <systemc>
#include <tlm>
#include <vcml/models/pci/host.h>  // NOLINT(build/include_order)
#include <vcml/protocols/gpio.h>   // NOLINT(build/include_order)

#include "spikes/pcie/vcml_parts.h"

namespace spike {

// The two borrowed models and what they need around them. Each wants a
// clock (which only sets how long an access is said to take) and a reset
// line. VCML calls tying a port off "stubbing" it.
struct VcmlEndpoint::Model {
  Model(VcmlEndpoint& owner, const Config& config)
      : endpoint_("endpoint", PciConfig(config)),
        bar0_size_(
            std::bit_ceil(config.function_size + MsixSize(config.vectors))) {
    // Outwards: VCML's TLM sockets are plain TLM sockets underneath, 32
    // bits wide like ours, so each binds to its counterpart on the adapter
    // directly, with nothing in between.
    owner.ecam.bind(host_.cfg_in);
    owner.mmio.bind(host_.mmio_in[0]);
    host_.dma_out.bind(owner.dma);
    endpoint_.bar_out[0].bind(owner.bar0);
    owner.function_dma.bind(endpoint_.dma_in);
    host_.dma_out.allow_dmi = config.dma_by_dmi;

    // Inwards: the endpoint is device 0, function 0 on the host's bus.
    host_.pci_out[vcml::pci_devno(0, 0)].bind(endpoint_.pci_in);

    // A wire becomes one of VCML's interrupt sockets through its adapter
    // module, which watches the wire from a process of its own.
    for (std::size_t vector = 0; vector < config.vectors; ++vector) {
      auto& line =
          lines_.emplace_back(std::make_unique<vcml::gpio_initiator_adapter>(
              ("irq_adapter" + std::to_string(vector)).c_str()));
      line->in.bind(owner.irq[vector]);
      line->out.bind(endpoint_.irq_in[vector]);
    }

    endpoint_.pci_declare_bar(0, bar0_size_,
                              vcml::PCI_BAR_MMIO | vcml::PCI_BAR_64);
    endpoint_.pci_declare_msix_cap(
        0, config.vectors, static_cast<vcml::u32>(config.function_size));

    host_.clk.stub(100 * vcml::MHz);
    host_.rst.stub();
    host_.irq_a.stub();
    host_.irq_b.stub();
    host_.irq_c.stub();
    host_.irq_d.stub();
    endpoint_.clk.stub(100 * vcml::MHz);
    endpoint_.rst.stub();
  }

  vcml::pci::host host_{"host", /*express=*/true};
  CorrectedEndpoint endpoint_;
  std::vector<std::unique_ptr<vcml::gpio_initiator_adapter>> lines_;
  std::uint64_t bar0_size_;
};

VcmlEndpoint::VcmlEndpoint(const sc_core::sc_module_name& name,
                           const Config& config)
    : sc_module(name),
      irq("irq", config.vectors),
      model_(std::make_unique<Model>(*this, config)) {}

VcmlEndpoint::~VcmlEndpoint() = default;

void VcmlEndpoint::before_end_of_elaboration() {
  for (auto& line : irq) {
    if (line.size() == 0) line.bind(tied_low_);
  }
}

void VcmlEndpoint::start_of_simulation() {
#ifndef SPIKE_VCML_AS_IS
  // VCML takes the thread that loaded it for the one the kernel runs on,
  // and stops the process when a transaction arrives on any other. This is
  // the kernel's thread, so tell it.
  vcml::set_sysc_thread();
#endif
}

}  // namespace spike
