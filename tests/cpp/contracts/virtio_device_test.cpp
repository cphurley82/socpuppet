#include <cstdint>
#include <memory>

#include <gtest/gtest.h>

#include "socpuppet/models/virtio_rng.h"
#include "tests/cpp/contracts/virtio_device_contract.h"
#include "tests/cpp/support/virtio_blk_rig.h"
#include "tests/cpp/support/virtio_console_rig.h"
#include "tests/cpp/support/virtio_net_rig.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace {

// The entropy device answers any buffer it can write to, with random bytes.
struct VirtioRngRig {
  using Device = socpuppet::VirtioRng;
  static constexpr std::uint16_t kAnswersOn = 0;
  static std::unique_ptr<Device> Make(const char* name) {
    return std::make_unique<Device>(name);
  }
  static void AChainItAnswers(VirtqueueDriver& driver) {
    driver.Describe(0, 16, VirtqueueDriver::kWrite);
    driver.MakeAvailable(0);
  }
};

}  // namespace

INSTANTIATE_TYPED_TEST_SUITE_P(VirtioRng, VirtioDeviceContract,
                               ::testing::Types<VirtioRngRig>);
INSTANTIATE_TYPED_TEST_SUITE_P(VirtioConsole, VirtioDeviceContract,
                               ::testing::Types<VirtioConsoleRig>);
INSTANTIATE_TYPED_TEST_SUITE_P(VirtioBlk, VirtioDeviceContract,
                               ::testing::Types<VirtioBlkRig>);
INSTANTIATE_TYPED_TEST_SUITE_P(VirtioNet, VirtioDeviceContract,
                               ::testing::Types<VirtioNetRig>);
