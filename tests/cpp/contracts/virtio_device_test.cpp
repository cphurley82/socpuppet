#include <gtest/gtest.h>

#include "socpuppet/models/virtio_rng.h"
#include "tests/cpp/contracts/virtio_device_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(VirtioRng, VirtioDeviceContract,
                               ::testing::Types<socpuppet::VirtioRng>);
