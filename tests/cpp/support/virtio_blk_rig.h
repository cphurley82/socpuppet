#ifndef TESTS_CPP_SUPPORT_VIRTIO_BLK_RIG_H_
#define TESTS_CPP_SUPPORT_VIRTIO_BLK_RIG_H_

#include <cstdint>
#include <memory>
#include <span>
#include <vector>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/virtio_blk_logic.h"
#include "socpuppet/models/virtio_blk.h"
#include "tests/cpp/support/virtqueue_driver.h"

// The block device under the virtio device contract, as a disk of eight
// sectors: it answers a request on its one queue at once, and a flush is
// the smallest request there is, a header and a status byte.
struct VirtioBlkRig {
  using Device = socpuppet::VirtioBlk;
  static constexpr std::uint16_t kAnswersOn = 0;
  static std::unique_ptr<Device> Make(const char* name) {
    return std::make_unique<Device>(name, std::uint64_t{8});
  }
  static void AChainItAnswers(VirtqueueDriver& driver) {
    std::vector<std::uint8_t> header(16);
    socpuppet::StoreLittleEndian(socpuppet::VirtioBlkLogic::kTypeFlush,
                                 std::span(header).first(4));
    driver.Describe(0, 16, VirtqueueDriver::kNext, 1);
    driver.Fill(0, header);
    driver.Describe(1, 1, VirtqueueDriver::kWrite);
    driver.MakeAvailable(0);
  }
};

#endif  // TESTS_CPP_SUPPORT_VIRTIO_BLK_RIG_H_
