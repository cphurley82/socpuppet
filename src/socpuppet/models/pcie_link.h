#ifndef SOCPUPPET_MODELS_PCIE_LINK_H_
#define SOCPUPPET_MODELS_PCIE_LINK_H_

#include <cstdint>

#include <systemc>
#include <tlm>

namespace socpuppet {

// A PCIe link is modelled as a pair of ordinary TLM sockets, one for each
// direction. The real link carries packets, and a packet says which of
// the device's address spaces it is for. That is the part a driver can
// observe, so it is the part kept here.
//
// There are two spaces. Memory is the function's own registers, wherever
// the host has placed them, and the host's memory when the device does
// DMA. A memory access is an ordinary transaction, whose address is the
// address on the host's bus. Configuration space is the 4 KiB of registers
// every function has, which say what it is and let the host set it up. A
// configuration access carries this extension, and its address is an
// offset into those registers.
//
// Not built yet: a packet also says which device sent it, and that will
// ride along here too once something needs to know.
struct PcieConfigurationAccess : tlm::tlm_extension<PcieConfigurationAccess> {
  tlm::tlm_extension_base* clone() const override {
    return new PcieConfigurationAccess(*this);
  }
  void copy_from(const tlm::tlm_extension_base&) override {}
};

// Makes a transaction a configuration access to the register at `offset`
// for as long as this is alive: send it down a link meanwhile. The
// transaction is the caller's again afterwards, with its own address back.
class AsConfigurationAccess {
 public:
  AsConfigurationAccess(tlm::tlm_generic_payload& transaction,
                        std::uint64_t offset)
      : transaction_(transaction), address_before_(transaction.get_address()) {
    transaction_.set_address(offset);
    transaction_.set_extension(&marker_);
  }
  ~AsConfigurationAccess() {
    transaction_.clear_extension(&marker_);
    transaction_.set_address(address_before_);
  }
  AsConfigurationAccess(const AsConfigurationAccess&) = delete;
  AsConfigurationAccess& operator=(const AsConfigurationAccess&) = delete;

 private:
  tlm::tlm_generic_payload& transaction_;
  std::uint64_t address_before_;
  PcieConfigurationAccess marker_;
};

// Whether a transaction that came down a link is a configuration access.
// Anything else is a memory access.
inline bool IsConfigurationAccess(const tlm::tlm_generic_payload& transaction) {
  const PcieConfigurationAccess* marker = nullptr;
  transaction.get_extension(marker);
  return marker != nullptr;
}

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_PCIE_LINK_H_
