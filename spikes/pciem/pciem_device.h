#ifndef SPIKES_PCIEM_PCIEM_DEVICE_H_
#define SPIKES_PCIEM_PCIEM_DEVICE_H_

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

// A PCIe device on this machine's own bus, played by this program through
// pciem's /dev/pciem. Only pciem_device.cpp includes pciem's header, which
// is GPL-2.0-only and needs C++23 for its <stdatomic.h>; everything else
// sees this.
//
// pciem's kernel side plays the device's configuration space and its MSI-X
// table, and puts each base address register (BAR) in memory set aside at
// boot. A host write to BAR0 lands in that memory (pciem's shadow write)
// and is posted on a ring for us. A host read never reaches us: it reads
// the memory, so what the host should read has to be put there first.

namespace spike {

// One write the host made to a BAR, as pciem posted it.
struct HostWrite {
  std::uint32_t bar = 0;
  std::uint64_t offset = 0;
  std::uint32_t size = 0;  // bytes: 1, 2, 4 or 8
  std::uint64_t data = 0;  // only the low `size` bytes mean anything
};

// What came off the ring in one drain.
struct Drained {
  std::size_t writes = 0;
  std::size_t other_events = 0;  // config-space accesses, resets and so on
};

// Moves everything posted on a pciem ring into `writes`, and frees the
// slots for the kernel. `ring` is a struct pciem_shared_ring. Separate
// from the device so that it can be tried on a ring in ordinary memory.
Drained DrainRing(void* ring, std::vector<HostWrite>& writes);

class PciemDevice {
 public:
  struct Shape {
    std::uint16_t vendor = 0;
    std::uint16_t device = 0;
    std::uint32_t bar0_size = 0;  // a power of two
    std::uint16_t vectors = 0;    // MSI-X vectors
  };

  // Creates the device and registers it, without starting it: the host
  // does not see it until Start(). Throws std::system_error, naming the
  // step, if /dev/pciem refuses one.
  explicit PciemDevice(const Shape& shape);
  ~PciemDevice();
  PciemDevice(const PciemDevice&) = delete;
  PciemDevice& operator=(const PciemDevice&) = delete;

  // Puts the device on the bus: the host enumerates it and its driver
  // binds. BAR0 should hold what the driver reads first, before this.
  void Start();

  // Readable when the kernel has posted something on the ring.
  int EventFd() const { return event_fd_; }
  // Clears EventFd()'s count and drains the ring.
  Drained Drain(std::vector<HostWrite>& writes);

  // BAR0's memory, as the host reads it.
  std::span<std::uint8_t> Bar0() { return {bar0_, bar0_size_}; }

  // Copies between the host's memory at `address` (an address the host
  // gave the device) and `data`. Throws std::system_error on refusal.
  void Dma(std::uint64_t address, std::span<std::uint8_t> data, bool to_host);
  // Sends MSI-X vector `vector`.
  void InjectIrq(unsigned vector);

 private:
  int fd_ = -1;
  int instance_fd_ = -1;
  int event_fd_ = -1;
  std::uint8_t* bar0_ = nullptr;
  std::size_t bar0_size_ = 0;
  void* ring_ = nullptr;
};

}  // namespace spike

#endif  // SPIKES_PCIEM_PCIEM_DEVICE_H_
