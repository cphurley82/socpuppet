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
  // The transport's own feature bit (section 6): the device speaks the
  // modern layout and nothing of the legacy one.
  static constexpr std::uint64_t kVersion1 = std::uint64_t{1} << 32;

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
      case VIRTIO_MMIO_DEVICE_FEATURES:
        StoreLittleEndian(
            Half(device_.Features() | kVersion1, device_features_sel_), out);
        return true;
      case VIRTIO_MMIO_STATUS:
        StoreLittleEndian(status_, out);
        return true;
      default:
        return false;
    }
  }

  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in) {
    const auto value = LoadLittleEndian<std::uint32_t>(in);
    switch (offset) {
      case VIRTIO_MMIO_DEVICE_FEATURES_SEL:
        device_features_sel_ = value;
        return true;
      case VIRTIO_MMIO_DRIVER_FEATURES_SEL:
        driver_features_sel_ = value;
        return true;
      case VIRTIO_MMIO_DRIVER_FEATURES:
        SetHalf(driver_features_, driver_features_sel_, value);
        return true;
      case VIRTIO_MMIO_STATUS:
        // The driver's features are taken only if the device offered every
        // one of them and the modern layout is among them (section 3.1.1);
        // otherwise FEATURES_OK is left clear for the driver to find.
        status_ = value;
        if (!FeaturesAcceptable()) status_ &= ~VIRTIO_MMIO_STATUS_FEATURES_OK;
        return true;
      default:
        return false;
    }
  }

 private:
  // Half `which` of 64 feature bits: the low 32 for zero, the high 32 for
  // one, and nothing for any other.
  static std::uint32_t Half(std::uint64_t bits, std::uint32_t which) {
    return which < 2 ? static_cast<std::uint32_t>(bits >> (32 * which)) : 0;
  }

  bool FeaturesAcceptable() const {
    const std::uint64_t offered = device_.Features() | kVersion1;
    return (driver_features_ & ~offered) == 0 &&
           (driver_features_ & kVersion1) != 0;
  }

  static void SetHalf(std::uint64_t& bits, std::uint32_t which,
                      std::uint32_t half) {
    if (which >= 2) return;
    const std::uint64_t mask = std::uint64_t{0xFFFF'FFFF} << (32 * which);
    bits = (bits & ~mask) | (std::uint64_t{half} << (32 * which));
  }

  VirtioDevice& device_;
  MemoryPort& memory_;
  std::uint32_t device_features_sel_ = 0;
  std::uint32_t driver_features_sel_ = 0;
  std::uint64_t driver_features_ = 0;
  std::uint32_t status_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_MMIO_LOGIC_H_
