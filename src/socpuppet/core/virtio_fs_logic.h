#ifndef SOCPUPPET_CORE_VIRTIO_FS_LOGIC_H_
#define SOCPUPPET_CORE_VIRTIO_FS_LOGIC_H_

#include <algorithm>
#include <array>
#include <cstddef>
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

// 🎭 A virtio file system device (virtio 1.2, section 5.11): a share the
// driver mounts by its tag, and talks to in FUSE, Linux's protocol for a
// file system served by a program. Each chain is one FUSE request, the
// readable buffers the request and the writable ones the room for its
// answer.
//
// The device knows nothing of FUSE: it hands each request's bytes to its
// answerer, whatever serves the share, and writes back what that gives.
// That is the split QEMU makes between its `vhost-user-fs-device` and the
// `virtiofsd` daemon behind it. What it leaves out: more than one request
// queue, the notification queue, and the DAX window that maps files
// straight into the guest's memory.
class VirtioFsLogic : public VirtioDevice {
 public:
  static constexpr std::uint32_t kDeviceId = 26;
  // FORGET, which has no answer, goes on the high-priority queue, and
  // everything else on the request queue.
  static constexpr std::uint16_t kHighPriorityQueue = 0;
  static constexpr std::uint16_t kRequestQueue = 1;
  // How long a tag may be: the configuration's 36 bytes, padded with
  // zeros and with none at the end if the tag fills them.
  static constexpr std::size_t kTagBytes = 36;

  // What serves the share: given a request's bytes, it gives the answer's,
  // or none for a request that has no answer.
  using Answerer =
      std::function<std::vector<std::uint8_t>(std::span<const std::uint8_t>)>;

  VirtioFsLogic() {
    StoreLittleEndian(std::uint32_t{1},
                      std::span(config_).subspan(kTagBytes, 4));
  }

  std::uint32_t DeviceId() const override { return kDeviceId; }
  std::uint64_t Features() const override { return 0; }
  std::uint16_t QueueCount() const override { return 2; }
  // The tag, and how many request queues there are: one.
  std::span<const std::uint8_t> Config() const override { return config_; }
  // A request is answered as it is handed over, so none is in flight.
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

  // Has `answerer` serve the share from now on. With none, every request
  // comes back with nothing written.
  void SetAnswerer(Answerer answerer) { answerer_ = std::move(answerer); }

  // Names the share `tag`, which the driver mounts it by. A tag longer
  // than the configuration holds is cut to fit.
  void SetTag(std::string_view tag) {
    const std::span<std::uint8_t> field = std::span(config_).first(kTagBytes);
    std::ranges::fill(field, std::uint8_t{0});
    std::ranges::copy(tag.substr(0, kTagBytes), field.begin());
  }

 private:
  std::array<std::uint8_t, kTagBytes + 4> config_{};
  Answerer answerer_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_VIRTIO_FS_LOGIC_H_
