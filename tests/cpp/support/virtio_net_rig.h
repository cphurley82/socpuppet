#ifndef TESTS_CPP_SUPPORT_VIRTIO_NET_RIG_H_
#define TESTS_CPP_SUPPORT_VIRTIO_NET_RIG_H_

#include <cstdint>
#include <memory>
#include <vector>

#include "socpuppet/core/virtio_net_logic.h"
#include "socpuppet/models/virtio_net.h"
#include "tests/cpp/support/virtqueue_driver.h"

// The network device under the virtio device contract: it answers a frame
// to send, on its transmit queue, at once; a buffer on its receive queue
// it keeps until a frame comes in.
struct VirtioNetRig {
  using Device = socpuppet::VirtioNet;
  static constexpr std::uint16_t kAnswersOn =
      socpuppet::VirtioNetLogic::kTransmitQueue;
  static constexpr std::uint64_t kMac = 0x0200'5E00'5301;
  static std::unique_ptr<Device> Make(const char* name) {
    return std::make_unique<Device>(name, kMac);
  }
  // A header and a frame of four bytes, in one buffer.
  static void AChainItAnswers(VirtqueueDriver& driver) {
    std::vector<std::uint8_t> bytes(socpuppet::VirtioNetLogic::kHeaderBytes, 0);
    bytes.insert(bytes.end(), {'s', 'p', 'a', 'm'});
    driver.Describe(0, static_cast<std::uint32_t>(bytes.size()),
                    VirtqueueDriver::kReadable);
    driver.Fill(0, bytes);
    driver.MakeAvailable(0);
  }
};

#endif  // TESTS_CPP_SUPPORT_VIRTIO_NET_RIG_H_
