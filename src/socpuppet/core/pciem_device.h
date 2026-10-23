#ifndef SOCPUPPET_CORE_PCIEM_DEVICE_H_
#define SOCPUPPET_CORE_PCIEM_DEVICE_H_

#include <cstdint>
#include <memory>
#include <span>
#include <vector>

#include "socpuppet/core/pcie_endpoint_registers.h"

// 🐧 A PCIe device on this machine's own bus, played by this program
// through pciem's /dev/pciem (https://github.com/cakehonolulu/pciem).
//
// pciem's kernel side plays the device's configuration space and its MSI-X
// table, and puts each base address register (BAR) in memory set aside at
// boot. A host write to BAR0 lands in that memory (pciem's shadow write)
// and is posted on a ring for us. A host read never reaches us: it reads
// the memory, so what the host should read has to be put there first.

// pciem's ring of what it has posted (include/pciem_api.h), by its name.
struct pciem_shared_ring;  // NOLINT(readability-identifier-naming)

namespace socpuppet {

// One write the host made to a BAR, as pciem posted it.
struct HostWrite {
  std::uint32_t bar = 0;
  std::uint64_t offset = 0;
  std::uint32_t size = 0;  // bytes: 1, 2, 4 or 8
  std::uint64_t data = 0;  // only the low `size` bytes mean anything
};

// What the device is on the bus: who it says it is, which the host's
// driver is picked by, how many bytes its register block takes (BAR0), and
// how many interrupt vectors it has.
struct PciemShape {
  PcieEndpointRegisters::Identity identity;
  std::uint64_t function_size = 0;
  std::uint16_t vectors = 0;
};

// What a PciemHost needs of the device: /dev/pciem in a run, a fake in the
// tests.
class PciemDevice {
 public:
  virtual ~PciemDevice() = default;

  // Puts the device on the bus: the host enumerates it, and its driver
  // binds. What the driver reads first should be in BAR0 before this.
  virtual void Start() = 0;

  // A descriptor that is readable when pciem has posted something.
  virtual int EventFd() const = 0;

  // Takes the host's writes that pciem has posted since the last drain,
  // in the order they were made, and clears pciem's word that something
  // was posted until more is. Whatever else pciem posts (the host's
  // accesses to configuration space, say) is dropped: pciem plays that.
  virtual std::vector<HostWrite> Drain() = 0;

  // pciem's copy of BAR0, which is what the host reads.
  virtual std::span<std::uint8_t> Bar0() = 0;

  // Copies between the host's memory at `address`, an address the host
  // gave the device, and `data`: into the host's memory if `to_host`, out
  // of it if not. Throws std::system_error if the host's side refuses.
  virtual void Dma(std::uint64_t address, std::span<std::uint8_t> data,
                   bool to_host) = 0;

  // Sends the host interrupt vector `vector`. Throws std::system_error if
  // pciem refuses. 🎓 pciem sends it as that vector's MSI-X message once
  // the host's driver has enabled MSI-X. On pciem's virtual bus it cannot,
  // so every vector reaches the host as the device's one legacy interrupt
  // (docs/upstream.md).
  virtual void InjectIrq(unsigned vector) = 0;
};

// pciem_device.cpp, in a build with pciem only: the one file that includes
// pciem's header, which is GPL-2.0-only and needs C++23.

// Takes the writes posted on a pciem ring, in the order they were posted,
// and frees their slots for the kernel. Separate from the device, so that
// it can be tried on a ring in ordinary memory.
std::vector<HostWrite> DrainRing(pciem_shared_ring& ring);

// Creates a device on this machine's bus, in `shape`, and registers it.
// Throws std::system_error, naming the step, if /dev/pciem refuses one.
std::unique_ptr<PciemDevice> OpenPciemDevice(const PciemShape& shape);

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_PCIEM_DEVICE_H_
