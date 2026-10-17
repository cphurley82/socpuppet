#ifndef SOCPUPPET_CORE_VIRTIO_MMIO_LOGIC_H_
#define SOCPUPPET_CORE_VIRTIO_MMIO_LOGIC_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <utility>
#include <vector>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/virtio_device.h"
#include "socpuppet/core/virtqueue.h"
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
  // The most entries a virtqueue may have, which is what QEMU's devices
  // allow too (section 2.7: at most 32768).
  static constexpr std::uint32_t kQueueSizeMax = 256;

  VirtioMmioLogic(VirtioDevice& device, MemoryPort& memory)
      : device_(device), memory_(memory), queues_(device.QueueCount()) {}

  // Reads and writes of the register block, by the driver. Each returns
  // false, and changes nothing, if the access is refused.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const {
    if (offset >= VIRTIO_MMIO_CONFIG) {
      const auto bytes = ConfigAt(offset - VIRTIO_MMIO_CONFIG, out.size());
      if (!bytes) return false;
      std::ranges::copy(*bytes, out.begin());
      return true;
    }
    if (!Aligned(offset, out.size())) return false;
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
        StoreLittleEndian(Half(Offered(), device_features_sel_), out);
        return true;
      case VIRTIO_MMIO_STATUS:
        StoreLittleEndian(status_, out);
        return true;
      case VIRTIO_MMIO_QUEUE_NUM_MAX:
        StoreLittleEndian(Selected() ? kQueueSizeMax : 0U, out);
        return true;
      case VIRTIO_MMIO_INTERRUPT_STATUS:
        StoreLittleEndian(interrupt_status_, out);
        return true;
      // No device here has shared memory, and all ones is how a region
      // that does not exist answers (section 4.2.2).
      case VIRTIO_MMIO_SHM_LEN_LOW:
        StoreLittleEndian(VIRTIO_MMIO_SHM_LEN_LOW_AT_RESET, out);
        return true;
      case VIRTIO_MMIO_SHM_LEN_HIGH:
        StoreLittleEndian(VIRTIO_MMIO_SHM_LEN_HIGH_AT_RESET, out);
        return true;
      case VIRTIO_MMIO_QUEUE_READY:
        StoreLittleEndian(
            Selected() && Selected()->ring ? VIRTIO_MMIO_QUEUE_READY_READY : 0U,
            out);
        return true;
      default:
        return false;
    }
  }

  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in) {
    if (offset >= VIRTIO_MMIO_CONFIG) {
      const auto bytes = ConfigAt(offset - VIRTIO_MMIO_CONFIG, in.size());
      if (!bytes) return false;
      std::ranges::copy(in, bytes->begin());
      return true;
    }
    if (!Aligned(offset, in.size())) return false;
    const auto value = LoadLittleEndian<std::uint32_t>(in);
    switch (offset) {
      case VIRTIO_MMIO_DEVICE_FEATURES_SEL:
        device_features_sel_ = value;
        return true;
      case VIRTIO_MMIO_DRIVER_FEATURES_SEL:
        driver_features_sel_ = value;
        return true;
      case VIRTIO_MMIO_QUEUE_SEL:
        queue_sel_ = value;
        return true;
      case VIRTIO_MMIO_QUEUE_NUM:
        if (!Selected() || value > kQueueSizeMax) return false;
        Selected()->layout.size = static_cast<std::uint16_t>(value);
        return true;
      case VIRTIO_MMIO_QUEUE_DESC_LOW:
        return SetHalfOf(&Queue::Layout::desc, 0, value);
      case VIRTIO_MMIO_QUEUE_DESC_HIGH:
        return SetHalfOf(&Queue::Layout::desc, 1, value);
      case VIRTIO_MMIO_QUEUE_DRIVER_LOW:
        return SetHalfOf(&Queue::Layout::avail, 0, value);
      case VIRTIO_MMIO_QUEUE_DRIVER_HIGH:
        return SetHalfOf(&Queue::Layout::avail, 1, value);
      case VIRTIO_MMIO_QUEUE_DEVICE_LOW:
        return SetHalfOf(&Queue::Layout::used, 0, value);
      case VIRTIO_MMIO_QUEUE_DEVICE_HIGH:
        return SetHalfOf(&Queue::Layout::used, 1, value);
      case VIRTIO_MMIO_QUEUE_READY:
        if (!Selected()) return false;
        if ((value & VIRTIO_MMIO_QUEUE_READY_READY) != 0) {
          Selected()->ring.emplace(memory_, Selected()->layout);
        } else {
          Selected()->ring.reset();
        }
        return true;
      case VIRTIO_MMIO_QUEUE_NOTIFY:
        if (value >= queues_.size() || !queues_[value].ring) return false;
        queues_[value].rung = true;
        return true;
      case VIRTIO_MMIO_INTERRUPT_ACK:
        interrupt_status_ &= ~value;
        return true;
      case VIRTIO_MMIO_SHM_SEL:
        return true;
      case VIRTIO_MMIO_DRIVER_FEATURES:
        SetHalf(driver_features_, driver_features_sel_, value);
        return true;
      case VIRTIO_MMIO_STATUS:
        if (value == 0) {
          Reset();
          return true;
        }
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

  // Does what the driver's doorbells asked for: hands every available chain
  // of every queue rung to the device. Returns whether anything was done.
  bool CarryOut() {
    bool done = false;
    for (std::uint16_t number = 0; number < queues_.size(); ++number) {
      Queue& queue = queues_[number];
      if (!queue.ring) continue;
      if (queue.rung) {
        queue.rung = false;
        while (std::optional<Virtqueue::Chain> chain = queue.ring->Next()) {
          device_.Handle(number, std::move(*chain), *queue.ring);
          done = true;
        }
      }
      // A chain may be given back while it is handled or later, from
      // wherever the device's answer comes from; either way the driver
      // hears of it here.
      if (queue.ring->UsedCount() != queue.used_reported) {
        queue.used_reported = queue.ring->UsedCount();
        interrupt_status_ |= VIRTIO_MMIO_INTERRUPT_STATUS_USED_BUFFER;
        done = true;
      }
    }
    return done;
  }

  // Whether the interrupt line is to be high.
  bool Interrupting() const { return interrupt_status_ != 0; }

 private:
  // One of the device's virtqueues, as the driver describes it through the
  // registers.
  struct Queue {
    using Layout = Virtqueue::Layout;
    Layout layout{.desc = 0, .avail = 0, .used = 0, .size = 0};
    // The queue itself, from when the driver says it is ready until it
    // says it is not.
    std::optional<Virtqueue> ring;
    // Whether the driver has rung its doorbell since the device last looked.
    bool rung = false;
    // How many used chains the driver has been interrupted for.
    std::uint16_t used_reported = 0;

    void Clear() {
      layout = Layout{.desc = 0, .avail = 0, .used = 0, .size = 0};
      ring.reset();
      rung = false;
      used_reported = 0;
    }
  };

  // The registers below the configuration are read and written as whole,
  // aligned 32-bit words and no other way (section 4.2.2.2).
  static bool Aligned(std::uint64_t offset, std::size_t size) {
    return size == kRegisterBytes && offset % kRegisterBytes == 0;
  }
  static constexpr std::size_t kRegisterBytes = 4;

  // The bytes of the device's configuration that an access of `size` bytes
  // at `offset` touches, or nothing if the access runs past the end of
  // what the device has. (The offset comes straight off the bus, so the
  // check is written not to overflow.)
  std::optional<std::span<std::uint8_t>> ConfigAt(std::uint64_t offset,
                                                  std::size_t size) const {
    const std::span<std::uint8_t> config = device_.Config();
    if (offset > config.size() || size > config.size() - offset) {
      return std::nullopt;
    }
    return config.subspan(offset, size);
  }

  // Writing zero to STATUS: everything the driver told the device is
  // forgotten, and the device drops what it was doing (section 2.4).
  void Reset() {
    for (Queue& queue : queues_) queue.Clear();
    driver_features_ = 0;
    device_features_sel_ = 0;
    driver_features_sel_ = 0;
    queue_sel_ = 0;
    interrupt_status_ = 0;
    status_ = 0;
    device_.Reset();
  }

  // The queue QUEUE_SEL names, if the device has one.
  Queue* Selected() {
    return queue_sel_ < queues_.size() ? &queues_[queue_sel_] : nullptr;
  }
  const Queue* Selected() const {
    return queue_sel_ < queues_.size() ? &queues_[queue_sel_] : nullptr;
  }

  // Sets half `which` of one of the selected queue's addresses.
  bool SetHalfOf(std::uint64_t Queue::Layout::* address, std::uint32_t which,
                 std::uint32_t half) {
    if (!Selected()) return false;
    SetHalf(Selected()->layout.*address, which, half);
    return true;
  }

  // Half `which` of 64 feature bits: the low 32 for zero, the high 32 for
  // one, and nothing for any other.
  static std::uint32_t Half(std::uint64_t bits, std::uint32_t which) {
    return which < 2 ? static_cast<std::uint32_t>(bits >> (32 * which)) : 0;
  }

  // What the device offers, with the transport's own bit.
  std::uint64_t Offered() const { return device_.Features() | kVersion1; }

  bool FeaturesAcceptable() const {
    return (driver_features_ & ~Offered()) == 0 &&
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
  std::uint32_t queue_sel_ = 0;
  std::vector<Queue> queues_;
  std::uint32_t interrupt_status_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_MMIO_LOGIC_H_
