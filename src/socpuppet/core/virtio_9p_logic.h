#ifndef SOCPUPPET_CORE_VIRTIO_9P_LOGIC_H_
#define SOCPUPPET_CORE_VIRTIO_9P_LOGIC_H_

#include <cstdint>
#include <functional>
#include <span>
#include <string_view>
#include <utility>
#include <vector>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/virtio_device.h"
#include "socpuppet/core/virtqueue.h"

namespace socpuppet {

// 🎭 A virtio 9P transport (device kind 9 in virtio 1.2's list, which has
// no section for it: the layout is Linux's, include/uapi/linux/virtio_9p.h,
// and QEMU's `virtio-9p-device` is the one most drivers have met): a share
// the driver mounts by its tag, and talks to in 9P2000.L, the dialect of Plan
// 9's file protocol that Linux's client speaks. Each chain is one 9P message,
// the readable buffers the T-message and the writable ones the room for its
// R-message.
//
// The device knows nothing of 9P: it hands each message's bytes to its
// answerer, whatever serves the share, and writes back what that gives,
// as VirtioFsLogic does with FUSE's requests. What it leaves out: nothing
// a driver can see, since the device has one queue, one feature and a
// configuration that is only its tag.
class Virtio9pLogic : public VirtioDevice {
 public:
  static constexpr std::uint32_t kDeviceId = 9;
  static constexpr std::uint16_t kRequestQueue = 0;
  // VIRTIO_9P_MOUNT_TAG: the configuration holds a tag. Linux's driver
  // will not take a device without it.
  static constexpr std::uint64_t kMountTag = 1U << 0;

  // What serves the share: given a T-message's bytes, it gives the
  // R-message's.
  using Answerer =
      std::function<std::vector<std::uint8_t>(std::span<const std::uint8_t>)>;

  std::uint32_t DeviceId() const override { return kDeviceId; }
  std::uint64_t Features() const override { return kMountTag; }
  std::uint16_t QueueCount() const override { return 1; }
  // The tag's length, two bytes, and then the tag, with nothing after it.
  std::span<const std::uint8_t> Config() const override { return config_; }
  // A message is answered as it is handed over, so none is in flight.
  void Reset() override {}

  void Handle(std::uint16_t /*queue*/, Virtqueue::Chain chain,
              Virtqueue& ring) override {
    if (!answerer_) {
      ring.Used(chain, 0);
      return;
    }
    const std::vector<std::uint8_t> answer = answerer_(ring.Read(chain));
    ring.Used(chain, ring.Write(chain, answer));
  }

  // Has `answerer` serve the share from now on. With none, every message
  // comes back with nothing written.
  void SetAnswerer(Answerer answerer) { answerer_ = std::move(answerer); }

  // Names the share `tag`, which the driver mounts it by.
  void SetTag(std::string_view tag) {
    config_.assign(2, 0);
    StoreLittleEndian(static_cast<std::uint16_t>(tag.size()),
                      std::span(config_));
    config_.insert(config_.end(), tag.begin(), tag.end());
  }

 private:
  std::vector<std::uint8_t> config_ = std::vector<std::uint8_t>(2);
  Answerer answerer_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_9P_LOGIC_H_
