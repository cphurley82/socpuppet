#ifndef SOCPUPPET_CORE_VIRTIO_CONSOLE_LOGIC_H_
#define SOCPUPPET_CORE_VIRTIO_CONSOLE_LOGIC_H_

#include <cstdint>
#include <deque>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "socpuppet/core/virtio_device.h"
#include "socpuppet/core/virtqueue.h"

namespace socpuppet {

// 🎭 A virtio console (virtio 1.2, section 5.3): a serial port with no
// baud rate. The driver hands bytes to put out on the transmit queue, and
// empty buffers on the receive queue for what comes in. One port, no
// features.
class VirtioConsoleLogic : public VirtioDevice {
 public:
  static constexpr std::uint32_t kDeviceId = 3;
  static constexpr std::uint16_t kReceiveQueue = 0;
  static constexpr std::uint16_t kTransmitQueue = 1;

  std::uint32_t DeviceId() const override { return kDeviceId; }
  std::uint64_t Features() const override { return 0; }
  std::uint16_t QueueCount() const override { return 2; }
  std::span<std::uint8_t> Config() override { return {}; }
  // The buffers it holds go with the queues they were in; what came in
  // and was not delivered waits on, as bytes still on the line would.
  void Reset() override { held_.clear(); }
  void Handle(std::uint16_t queue, Virtqueue::Chain chain,
              Virtqueue& ring) override {
    if (queue == kTransmitQueue) {
      const std::vector<std::uint8_t> bytes = ring.Read(chain);
      output_.append(bytes.begin(), bytes.end());
      ring.Used(chain, 0);
    } else {
      held_.push_back({std::move(chain), &ring});
    }
  }

  // Everything the driver has put out so far.
  const std::string& Output() const { return output_; }

  // Bytes that come in from the far end, as if typed. They wait here until
  // the driver has a buffer for them and the transport's `Deliver` puts
  // them in it.
  void Receive(std::string_view received) { received_.append(received); }

  // Puts what has come in into the buffers the driver has handed over, in
  // the order it handed them over, each filled before the next.
  void Deliver() {
    while (!received_.empty() && !held_.empty()) {
      const Held& held = held_.front();
      const std::span<const std::uint8_t> bytes{
          reinterpret_cast<const std::uint8_t*>(received_.data()),
          received_.size()};
      const std::uint32_t went = held.ring->Write(held.chain, bytes);
      held.ring->Used(held.chain, went);
      received_.erase(0, went);
      held_.pop_front();
    }
  }

 private:
  // A receive buffer the driver handed over, and the queue it is on.
  struct Held {
    Virtqueue::Chain chain;
    Virtqueue* ring;
  };

  std::string output_;
  std::string received_;
  std::deque<Held> held_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_CONSOLE_LOGIC_H_
