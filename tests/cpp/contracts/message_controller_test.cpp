#include <gtest/gtest.h>

#include "socpuppet/models/imsic.h"
#include "tests/cpp/contracts/message_controller_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Imsic, MessageControllerContract,
                               ::testing::Types<socpuppet::Imsic>);
