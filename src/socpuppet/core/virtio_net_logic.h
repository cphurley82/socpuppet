#ifndef SOCPUPPET_CORE_VIRTIO_NET_LOGIC_H_
#define SOCPUPPET_CORE_VIRTIO_NET_LOGIC_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <span>
#include <utility>
#include <vector>

#include "socpuppet/core/virtio_device.h"
#include "socpuppet/core/virtqueue.h"

namespace socpuppet {

// 🎭 A virtio network device (virtio 1.2, section 5.1): an Ethernet port
// whose wire is whoever holds the device. The driver hands it frames to
// send on the transmit queue, and empty buffers on the receive queue for
// the frames that come in. Every frame has a 12-byte header in front of
// it, both ways, for offloads this device offers none of.
//
// It stands for QEMU's `virtio-net-device` on the `virt` machine, with
// one pair of queues and its MAC address in the configuration, and
// leaves out everything a driver can do without: checksum and
// segmentation offloads, merged receive buffers, a control queue, a link
// status (a driver that is not offered one takes the link to be up).
class VirtioNetLogic : public VirtioDevice {
 public:
  static constexpr std::uint32_t kDeviceId = 1;
  static constexpr std::uint16_t kReceiveQueue = 0;
  static constexpr std::uint16_t kTransmitQueue = 1;
  // VIRTIO_NET_F_MAC: the address is in the configuration. EDK2's driver
  // will not bind without it; Zephyr's takes its address from the
  // devicetree instead.
  static constexpr std::uint64_t kFeatureMac = std::uint64_t{1} << 5U;
  // The header in front of every frame (section 5.1.6), the size it has
  // whenever VIRTIO_F_VERSION_1 is agreed, which this transport insists
  // on: flags, the offload's fields, and num_buffers last.
  static constexpr std::size_t kHeaderBytes = 12;

  using Frame = std::vector<std::uint8_t>;

  // `mac` is the device's address as a 48-bit number, its first byte
  // highest: 0x0200'5E00'5301 is 02:00:5e:00:53:01.
  explicit VirtioNetLogic(std::uint64_t mac) {
    for (std::size_t byte = 0; byte < mac_.size(); ++byte) {
      mac_[byte] = static_cast<std::uint8_t>(mac >> (8 * (5 - byte)));
    }
  }

  std::uint32_t DeviceId() const override { return kDeviceId; }
  std::uint64_t Features() const override { return kFeatureMac; }
  std::uint16_t QueueCount() const override { return 2; }
  // The configuration a driver reads with no feature but MAC: the
  // address, six bytes.
  std::span<const std::uint8_t> Config() const override { return mac_; }
  // The buffers held out are the driver's no longer. Frames waiting to
  // come in stay, as they would on a wire.
  void Reset() override { held_.clear(); }

  void Handle(std::uint16_t queue, Virtqueue::Chain chain,
              Virtqueue& ring) override {
    if (queue == kTransmitQueue) {
      const Frame bytes = ring.Read(chain);
      // A chain too short for a header has no frame in it.
      if (bytes.size() >= kHeaderBytes) {
        transmitted_.emplace_back(bytes.begin() + kHeaderBytes, bytes.end());
      }
      ring.Used(chain, 0);
    } else {
      held_.push_back({.chain = std::move(chain), .ring = &ring});
    }
  }

  // Every frame the driver has sent, without its header, in order.
  const std::vector<Frame>& Transmitted() const { return transmitted_; }

  // A frame comes in on the wire. It goes into the next buffer the driver
  // holds out, at the next delivery.
  void Receive(Frame frame) { incoming_.push_back(std::move(frame)); }

  // How many frames that came in were longer than the buffer they were
  // for, and were dropped, as a card drops a frame it has no room for.
  std::size_t Dropped() const { return dropped_; }

  void Deliver() override {
    while (!incoming_.empty() && !held_.empty()) {
      const Frame& frame = incoming_.front();
      Held& held = held_.front();
      if (kHeaderBytes + frame.size() > held.chain.WritableBytes()) {
        dropped_ += 1;
        incoming_.pop_front();
        continue;
      }
      std::vector<std::uint8_t> bytes(kHeaderBytes, 0);
      bytes[kNumBuffers] = 1;  // the whole frame is in this one buffer
      bytes.insert(bytes.end(), frame.begin(), frame.end());
      held.ring->Used(held.chain, held.ring->Write(held.chain, bytes));
      incoming_.pop_front();
      held_.pop_front();
    }
  }

 private:
  // Where num_buffers is in the header, little-endian.
  static constexpr std::size_t kNumBuffers = 10;

  // A receive buffer the driver has held out, and the ring to give it
  // back on.
  struct Held {
    Virtqueue::Chain chain;
    Virtqueue* ring;
  };

  std::array<std::uint8_t, 6> mac_{};
  std::vector<Frame> transmitted_;
  std::deque<Frame> incoming_;
  std::deque<Held> held_;
  std::size_t dropped_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_NET_LOGIC_H_
