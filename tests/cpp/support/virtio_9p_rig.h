#ifndef TESTS_CPP_SUPPORT_VIRTIO_9P_RIG_H_
#define TESTS_CPP_SUPPORT_VIRTIO_9P_RIG_H_

#include <cstdint>
#include <memory>
#include <span>
#include <vector>

#include "socpuppet/core/virtio_9p_logic.h"
#include "socpuppet/models/virtio_9p.h"
#include "tests/cpp/support/virtqueue_driver.h"

// The 9P transport under the virtio device contract, with an answerer
// that answers every message with sixteen bytes: a message on its queue
// comes back at once.
struct Virtio9pRig {
  using Device = socpuppet::Virtio9p;
  static constexpr std::uint16_t kAnswersOn =
      socpuppet::Virtio9pLogic::kRequestQueue;
  static std::unique_ptr<Device> Make(const char* name) {
    auto device = std::make_unique<Device>(name);
    device->SetAnswerer([](std::span<const std::uint8_t> /*message*/) {
      return std::vector<std::uint8_t>(16, 0);
    });
    return device;
  }
  // A message of four bytes, and room for the answer.
  static void AChainItAnswers(VirtqueueDriver& driver) {
    driver.Describe(0, 4, VirtqueueDriver::kNext, 1);
    driver.Fill(0, std::vector<std::uint8_t>{'s', 'p', 'a', 'm'});
    driver.Describe(1, 16, VirtqueueDriver::kWrite);
    driver.MakeAvailable(0);
  }
};

#endif  // TESTS_CPP_SUPPORT_VIRTIO_9P_RIG_H_
