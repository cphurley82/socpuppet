#ifndef SOCPUPPET_CORE_VIRTIO_RNG_LOGIC_H_
#define SOCPUPPET_CORE_VIRTIO_RNG_LOGIC_H_

#include <cstddef>
#include <cstdint>
#include <random>
#include <span>
#include <vector>

#include "socpuppet/core/virtio_device.h"
#include "socpuppet/core/virtqueue.h"

namespace socpuppet {

// 🎭 A virtio entropy device (virtio 1.2, section 5.4): the driver hands
// it empty buffers and it fills them with random bytes. One queue, no
// features and no configuration, which makes it the smallest virtio
// device there is. The bytes come from a generator seeded by whoever
// built the device, so a run can be repeated.
class VirtioRngLogic : public VirtioDevice {
 public:
  static constexpr std::uint32_t kDeviceId = 4;

  explicit VirtioRngLogic(std::uint64_t seed = 1) : generator_(seed) {}

  std::uint32_t DeviceId() const override { return kDeviceId; }
  std::uint64_t Features() const override { return 0; }
  std::uint16_t QueueCount() const override { return 1; }
  std::span<const std::uint8_t> Config() const override { return {}; }
  // Nothing is in flight to drop: a chain is answered as it is handed
  // over. The generator carries on, so a driver that resets does not get
  // the same bytes twice.
  void Reset() override {}
  void Handle(std::uint16_t /*queue*/, Virtqueue::Chain chain,
              Virtqueue& ring) override {
    std::size_t asked = 0;
    for (const Virtqueue::Buffer& buffer : chain.writable) {
      asked += buffer.length;
    }
    std::vector<std::uint8_t> bytes(asked);
    for (std::uint8_t& byte : bytes) {
      byte = static_cast<std::uint8_t>(generator_());
    }
    ring.Used(chain, ring.Write(chain, bytes));
  }

 private:
  std::mt19937_64 generator_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_RNG_LOGIC_H_
