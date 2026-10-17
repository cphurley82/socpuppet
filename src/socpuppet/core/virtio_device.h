#ifndef SOCPUPPET_CORE_VIRTIO_DEVICE_H_
#define SOCPUPPET_CORE_VIRTIO_DEVICE_H_

#include <cstdint>
#include <span>

#include "socpuppet/core/virtqueue.h"

namespace socpuppet {

// What a virtio device is, as the transport sees it: the part of a device
// that is its own, behind the register block and the virtqueues every
// device shares (virtio 1.2, section 2). A device's logic implements this
// with no simulator in it, and the transport's logic drives it.
class VirtioDevice {
 public:
  virtual ~VirtioDevice() = default;

  // What the device is, by the specification's numbering (section 5).
  virtual std::uint32_t DeviceId() const = 0;

  // The feature bits the device offers, its own and none of the
  // transport's: `VERSION_1` is the transport's to add.
  virtual std::uint64_t Features() const = 0;

  // How many virtqueues the device has, numbered from zero.
  virtual std::uint16_t QueueCount() const = 0;

  // A chain the driver has made available on queue `queue`. The device
  // reads and writes it through `ring`, and gives it back with
  // `ring.Used()`, now or later.
  virtual void Handle(std::uint16_t queue, Virtqueue::Chain chain,
                      Virtqueue& ring) = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_DEVICE_H_
