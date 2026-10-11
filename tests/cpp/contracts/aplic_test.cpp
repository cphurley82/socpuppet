#include "socpuppet/models/aplic.h"

#include <gtest/gtest.h>

#include "tests/cpp/contracts/aplic_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Aplic, AplicContract,
                               ::testing::Types<socpuppet::Aplic>);
