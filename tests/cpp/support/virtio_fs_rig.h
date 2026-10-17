#ifndef TESTS_CPP_SUPPORT_VIRTIO_FS_RIG_H_
#define TESTS_CPP_SUPPORT_VIRTIO_FS_RIG_H_

#include <cstdint>
#include <memory>
#include <span>
#include <vector>

#include "socpuppet/core/virtio_fs_logic.h"
#include "socpuppet/models/virtio_fs.h"
#include "tests/cpp/support/virtqueue_driver.h"

// The file system device under the virtio device contract, with an
// answerer that answers every request with sixteen bytes: a request on its
// request queue comes back at once.
struct VirtioFsRig {
  using Device = socpuppet::VirtioFs;
  static constexpr std::uint16_t kAnswersOn =
      socpuppet::VirtioFsLogic::kRequestQueue;
  static std::unique_ptr<Device> Make(const char* name) {
    auto device = std::make_unique<Device>(name);
    device->SetAnswerer([](std::span<const std::uint8_t> /*request*/) {
      return std::vector<std::uint8_t>(16, 0);
    });
    return device;
  }
  // A request of four bytes, and room for the answer.
  static void AChainItAnswers(VirtqueueDriver& driver) {
    driver.Describe(0, 4, VirtqueueDriver::kNext, 1);
    driver.Fill(0, std::vector<std::uint8_t>{'s', 'p', 'a', 'm'});
    driver.Describe(1, 16, VirtqueueDriver::kWrite);
    driver.MakeAvailable(0);
  }
};

#endif  // TESTS_CPP_SUPPORT_VIRTIO_FS_RIG_H_
