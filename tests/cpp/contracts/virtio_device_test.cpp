#include <gtest/gtest.h>

#include "socpuppet/models/virtio_rng.h"
#include "tests/cpp/contracts/virtio_device_contract.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace {

// The entropy device answers any buffer it can write to, with random bytes.
struct VirtioRngRig {
  using Device = socpuppet::VirtioRng;
  static void AChainItAnswers(VirtqueueDriver& driver) {
    driver.Describe(0, 16, VirtqueueDriver::kWrite);
    driver.MakeAvailable(0);
  }
};

}  // namespace

INSTANTIATE_TYPED_TEST_SUITE_P(VirtioRng, VirtioDeviceContract,
                               ::testing::Types<VirtioRngRig>);
