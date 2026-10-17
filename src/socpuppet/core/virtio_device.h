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
  // `ring.Used()`, now or later. A device that keeps the chain for later
  // may keep `ring` with it: the reference is good until `Reset()`, which
  // is the only way the transport takes a ring away from a device that
  // holds one.
  virtual void Handle(std::uint16_t queue, Virtqueue::Chain chain,
                      Virtqueue& ring) = 0;

  // What has come to the device from outside the driver's memory since it
  // last looked (a console's typed bytes, a network's frames), handed into
  // the chains it holds. The transport asks each time it carries out, which
  // the shell has it do when the far end says something has come.
  virtual void Deliver() {}

  // The driver has reset the device: whatever it was doing is dropped, and
  // the chains it was holding with it.
  virtual void Reset() = 0;

  // The device's own configuration, which the driver reads at any width
  // from `CONFIG` on (section 4.2.2). Empty for a device with none.
  virtual std::span<const std::uint8_t> Config() const = 0;

  // The driver writes `bytes` at `offset` in the configuration, inside
  // it. Most fields are read-only, and a write to one is dropped, as
  // QEMU's devices drop it; a device with a field the driver may write
  // takes the write here.
  virtual void WriteConfig(std::uint64_t /*offset*/,
                           std::span<const std::uint8_t> /*bytes*/) {}
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_DEVICE_H_
