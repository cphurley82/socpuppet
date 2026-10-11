#include "socpuppet/models/rom.h"

#include "tests/cpp/contracts/rom_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Rom, RomContract,
                               ::testing::Types<socpuppet::Rom>);
