#ifndef SOCPUPPET_MODELS_PCIE_LINK_H_
#define SOCPUPPET_MODELS_PCIE_LINK_H_

#include <cstdint>
#include <optional>

#include <systemc>
#include <tlm>

#include "socpuppet/platform/transport.h"

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
// A packet a function sends up the link also says who sent it, and that
// rides along too, as PcieRequesterId below.
struct PcieConfigurationAccess : tlm::tlm_extension<PcieConfigurationAccess> {
  explicit PcieConfigurationAccess(std::uint16_t function) : to(function) {}
  tlm::tlm_extension_base* clone() const override {
    return new PcieConfigurationAccess(*this);
  }
  void copy_from(const tlm::tlm_extension_base& other) override {
    to = static_cast<const PcieConfigurationAccess&>(other).to;
  }

  // Which function the access is for: its bus, device and function
  // numbers, packed as a requester ID is.
  std::uint16_t to;
};

// Makes a transaction a configuration access to the register at `offset`
// of the function `to`, by its bus, device and function numbers packed as a
// requester ID is, for as long as this is alive: send it down a link
// meanwhile. The transaction is the caller's again afterwards, with its own
// address back.
class AsConfigurationAccess {
 public:
  AsConfigurationAccess(tlm::tlm_generic_payload& transaction,
                        std::uint64_t offset, std::uint16_t to)
      : transaction_(transaction),
        at_the_register_(transaction, offset),
        marker_(to) {
    transaction_.set_extension(&marker_);
  }
  ~AsConfigurationAccess() { transaction_.clear_extension(&marker_); }
  AsConfigurationAccess(const AsConfigurationAccess&) = delete;
  AsConfigurationAccess& operator=(const AsConfigurationAccess&) = delete;

 private:
  tlm::tlm_generic_payload& transaction_;
  AtAddress at_the_register_;
  PcieConfigurationAccess marker_;
};

// What makes a transaction that came down a link a configuration access,
// or null for a memory access.
inline const PcieConfigurationAccess* ConfigurationAccessOf(
    const tlm::tlm_generic_payload& transaction) {
  const PcieConfigurationAccess* marker = nullptr;
  transaction.get_extension(marker);
  return marker;
}

// Whether a transaction that came down a link is a configuration access.
// Anything else is a memory access.
inline bool IsConfigurationAccess(const tlm::tlm_generic_payload& transaction) {
  return ConfigurationAccessOf(transaction) != nullptr;
}

// Which function sent a transaction up a link: its requester ID, which is
// its bus, device and function numbers as bus << 8 | device << 3 |
// function. An IOMMU looks a device up by it.
struct PcieRequesterId : tlm::tlm_extension<PcieRequesterId> {
  explicit PcieRequesterId(std::uint16_t requester) : id(requester) {}
  tlm::tlm_extension_base* clone() const override {
    return new PcieRequesterId(*this);
  }
  void copy_from(const tlm::tlm_extension_base& other) override {
    id = static_cast<const PcieRequesterId&>(other).id;
  }

  std::uint16_t id;
};

// Marks a transaction as sent by the function with requester ID `id` for
// as long as this is alive: send it up a link meanwhile. The transaction is
// the caller's again afterwards, unmarked.
class AsFromRequester {
 public:
  AsFromRequester(tlm::tlm_generic_payload& transaction, std::uint16_t id)
      : transaction_(transaction), marker_(id) {
    transaction_.set_extension(&marker_);
  }
  ~AsFromRequester() { transaction_.clear_extension(&marker_); }
  AsFromRequester(const AsFromRequester&) = delete;
  AsFromRequester& operator=(const AsFromRequester&) = delete;

 private:
  tlm::tlm_generic_payload& transaction_;
  PcieRequesterId marker_;
};

// Which function sent a transaction that came up a link, or nothing if it
// does not say.
inline std::optional<std::uint16_t> RequesterIdOf(
    const tlm::tlm_generic_payload& transaction) {
  const PcieRequesterId* requester = nullptr;
  transaction.get_extension(requester);
  if (requester == nullptr) return std::nullopt;
  return requester->id;
}

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_PCIE_LINK_H_
