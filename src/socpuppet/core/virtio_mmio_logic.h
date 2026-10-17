#ifndef SOCPUPPET_CORE_VIRTIO_MMIO_LOGIC_H_
#define SOCPUPPET_CORE_VIRTIO_MMIO_LOGIC_H_

#include <cstddef>
#include <cstdint>
#include <span>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/virtio_device.h"
#include "socpuppet/regs/virtio_mmio.h"

namespace socpuppet {

// What the virtio-mmio transport does, with no simulator attached: the
// register block every virtio device sits behind (regs/virtio_mmio.rdl),
// the feature negotiation, the virtqueues and the interrupt, for one
// device (virtio 1.2, section 4.2).
class VirtioMmioLogic {
 public:
  // Who made the device: the letters SP.
  static constexpr std::uint32_t kVendorId = 0x5350;

  VirtioMmioLogic(VirtioDevice& device, MemoryPort& memory)
      : device_(device), memory_(memory) {}

  // Reads and writes of the register block, by the driver. Each returns
  // false, and changes nothing, if the access is refused.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const {
    switch (offset) {
      case VIRTIO_MMIO_MAGIC_VALUE:
        StoreLittleEndian(VIRTIO_MMIO_MAGIC_VALUE_AT_RESET, out);
        return true;
      case VIRTIO_MMIO_VERSION:
        StoreLittleEndian(VIRTIO_MMIO_VERSION_AT_RESET, out);
        return true;
      case VIRTIO_MMIO_DEVICE_ID:
        StoreLittleEndian(device_.DeviceId(), out);
        return true;
      case VIRTIO_MMIO_VENDOR_ID:
        StoreLittleEndian(kVendorId, out);
        return true;
      default:
        return false;
    }
  }

 private:
  VirtioDevice& device_;
  MemoryPort& memory_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_MMIO_LOGIC_H_
