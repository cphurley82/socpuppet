#include "spikes/pcie/vcml_bare_endpoint.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

// cpplint takes some of VCML's directories for the C library's.
#include <systemc>
#include <tlm>
#include <vcml/core/module.h>     // NOLINT(build/include_order)
#include <vcml/protocols/gpio.h>  // NOLINT(build/include_order)
#include <vcml/protocols/pci.h>   // NOLINT(build/include_order)

#include "spikes/pcie/vcml_parts.h"

namespace spike {

namespace {

// The largest access VCML's PCI payload can carry: its data is one 64-bit
// integer.
constexpr unsigned kLargestAccess = 8;

}  // namespace

// The borrowed endpoint, and the adapter standing where VCML expects a PCI
// host. VCML finds the host of a PCI socket by looking up the module
// hierarchy for a `pci_initiator`, so the stand-in for the host has to be a
// module of VCML's kind that owns the socket.
struct VcmlBareEndpoint::Model : vcml::module, vcml::pci_initiator {
  Model(const sc_core::sc_module_name& name, VcmlBareEndpoint& owner,
        const Config& config)
      : module(name), owner_(owner), endpoint_("endpoint", PciConfig(config)) {
    to_endpoint_.bind(endpoint_.pci_in);
    endpoint_.bar_out[0].bind(owner.bar0);
    owner.function_dma.bind(endpoint_.dma_in);
    for (std::size_t vector = 0; vector < config.vectors; ++vector) {
      auto& line =
          lines_.emplace_back(std::make_unique<vcml::gpio_initiator_adapter>(
              ("irq_adapter" + std::to_string(vector)).c_str()));
      line->in.bind(owner.irq[vector]);
      line->out.bind(endpoint_.irq_in[vector]);
    }
    const std::uint64_t bar0_size =
        std::bit_ceil(config.function_size + MsixSize(config.vectors));
    endpoint_.pci_declare_bar(0, bar0_size,
                              vcml::PCI_BAR_MMIO | vcml::PCI_BAR_64);
    endpoint_.pci_declare_msix_cap(
        0, config.vectors, static_cast<vcml::u32>(config.function_size));
    endpoint_.clk.stub(100 * vcml::MHz);
    endpoint_.rst.stub();
  }

  // A configuration access: `transaction` is addressed by ECAM offset, and
  // the endpoint is function 00:00.0. Any other function is absent, which
  // reads as all ones and is not an error.
  void Configure(tlm::tlm_generic_payload& transaction, bool debug) {
    if (transaction.get_address() >> 12 != 0) {
      if (transaction.is_read()) {
        std::fill_n(transaction.get_data_ptr(), transaction.get_data_length(),
                    static_cast<unsigned char>(0xFF));
      }
      transaction.set_response_status(tlm::TLM_OK_RESPONSE);
      return;
    }
    Send(transaction, vcml::PCI_AS_CFG, transaction.get_address(), debug);
    // A register the function does not have is reserved: zero, no error.
    if (transaction.get_response_status() == tlm::TLM_ADDRESS_ERROR_RESPONSE) {
      if (transaction.is_read()) {
        std::fill_n(transaction.get_data_ptr(), transaction.get_data_length(),
                    static_cast<unsigned char>(0));
      }
      transaction.set_response_status(tlm::TLM_OK_RESPONSE);
    }
  }

  // A memory access, addressed by PCI bus address: it goes to whichever
  // BAR has been placed there.
  void AccessMemory(tlm::tlm_generic_payload& transaction, bool debug) {
    const std::uint64_t first = transaction.get_address();
    const std::uint64_t last = first + transaction.get_data_length() - 1;
    for (const vcml::pci_bar& bar : placed_) {
      if (bar.size != 0 && first >= bar.addr && last < bar.addr + bar.size) {
        const auto space =
            static_cast<vcml::pci_address_space>(vcml::PCI_AS_BAR0 + bar.barno);
        Send(transaction, space, first - bar.addr, debug);
        return;
      }
    }
    transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
  }

 private:
  // One generic payload in, one of VCML's PCI payloads across, and the
  // answer back.
  void Send(tlm::tlm_generic_payload& transaction,
            vcml::pci_address_space space, std::uint64_t address, bool debug) {
    const unsigned length = transaction.get_data_length();
    if (length == 0 || length > kLargestAccess) {
      transaction.set_response_status(tlm::TLM_COMMAND_ERROR_RESPONSE);
      return;
    }
    vcml::pci_payload pci{};
    pci.command = transaction.is_read() ? vcml::PCI_READ : vcml::PCI_WRITE;
    pci.space = space;
    pci.addr = address;
    pci.size = length;
    pci.debug = debug;
    if (transaction.is_write()) {
      std::memcpy(&pci.data, transaction.get_data_ptr(), length);
    }
    to_endpoint_.transport(pci);
    if (transaction.is_read()) {
      std::memcpy(transaction.get_data_ptr(), &pci.data, length);
    }
    transaction.set_response_status(vcml::pci_translate_response(pci.response));
  }

  // vcml::pci_initiator: what the endpoint asks of its host.
  void pci_bar_map(const vcml::pci_initiator_socket&,
                   const vcml::pci_bar& bar) override {
    placed_.at(static_cast<std::size_t>(bar.barno)) = bar;
  }
  void pci_bar_unmap(const vcml::pci_initiator_socket&, int barno) override {
    placed_.at(static_cast<std::size_t>(barno)) = {};
  }
  // No direct memory access for DMA: every access is a transaction.
  void* pci_dma_ptr(const vcml::pci_initiator_socket&, vcml::vcml_access,
                    vcml::u64, vcml::u64) override {
    return nullptr;
  }
  bool pci_dma_read(const vcml::pci_initiator_socket&, vcml::u64 address,
                    vcml::u64 size, void* data) override {
    return Dma(tlm::TLM_READ_COMMAND, address, data, size);
  }
  bool pci_dma_write(const vcml::pci_initiator_socket&, vcml::u64 address,
                     vcml::u64 size, const void* data) override {
    return Dma(tlm::TLM_WRITE_COMMAND, address, const_cast<void*>(data), size);
  }
  // The legacy interrupt pins, which this endpoint does not have.
  void pci_interrupt(const vcml::pci_initiator_socket&, vcml::pci_irq,
                     bool) override {}
  void pci_dmi_invalidate(const vcml::pci_initiator_socket&, int, vcml::u64,
                          vcml::u64) override {}

  // The function's DMA and the MSI-X messages, each as one transaction.
  bool Dma(tlm::tlm_command command, std::uint64_t address, void* data,
           std::uint64_t size) {
    tlm::tlm_generic_payload transaction;
    transaction.set_command(command);
    transaction.set_address(address);
    transaction.set_data_ptr(static_cast<unsigned char*>(data));
    transaction.set_data_length(static_cast<unsigned>(size));
    transaction.set_streaming_width(static_cast<unsigned>(size));
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    owner_.dma->b_transport(transaction, delay);
    return transaction.is_response_ok();
  }

  VcmlBareEndpoint& owner_;
  vcml::pci_initiator_socket to_endpoint_{"to_endpoint"};
  CorrectedEndpoint endpoint_;
  std::vector<std::unique_ptr<vcml::gpio_initiator_adapter>> lines_;
  // Where each BAR is on the PCI bus. A size of zero is a BAR that is not
  // placed.
  std::array<vcml::pci_bar, vcml::PCI_NUM_BARS> placed_{};
};

VcmlBareEndpoint::VcmlBareEndpoint(const sc_core::sc_module_name& name,
                                   const Config& config)
    : sc_module(name),
      irq("irq", config.vectors),
      model_(std::make_unique<Model>("model", *this, config)) {
  ecam.register_b_transport(this, &VcmlBareEndpoint::Configure);
  ecam.register_transport_dbg(this, &VcmlBareEndpoint::DebugConfigure);
  mmio.register_b_transport(this, &VcmlBareEndpoint::AccessMemory);
  mmio.register_transport_dbg(this, &VcmlBareEndpoint::DebugAccessMemory);
}

void VcmlBareEndpoint::Configure(tlm::tlm_generic_payload& transaction,
                                 sc_core::sc_time&) {
  model_->Configure(transaction, /*debug=*/false);
}

unsigned VcmlBareEndpoint::DebugConfigure(
    tlm::tlm_generic_payload& transaction) {
  model_->Configure(transaction, /*debug=*/true);
  return transaction.is_response_ok() ? transaction.get_data_length() : 0;
}

void VcmlBareEndpoint::AccessMemory(tlm::tlm_generic_payload& transaction,
                                    sc_core::sc_time&) {
  model_->AccessMemory(transaction, /*debug=*/false);
}

unsigned VcmlBareEndpoint::DebugAccessMemory(
    tlm::tlm_generic_payload& transaction) {
  model_->AccessMemory(transaction, /*debug=*/true);
  return transaction.is_response_ok() ? transaction.get_data_length() : 0;
}

VcmlBareEndpoint::~VcmlBareEndpoint() = default;

void VcmlBareEndpoint::before_end_of_elaboration() {
  for (auto& line : irq) {
    if (line.size() == 0) line.bind(tied_low_);
  }
}

void VcmlBareEndpoint::start_of_simulation() { vcml::set_sysc_thread(); }

}  // namespace spike
