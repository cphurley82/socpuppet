#include <gtest/gtest.h>

#include "socpuppet/models/plic.h"
#include "tests/cpp/contracts/interrupt_controller_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Plic, InterruptControllerContract,
                               ::testing::Types<socpuppet::Plic>);
