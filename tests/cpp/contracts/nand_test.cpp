#include "socpuppet/models/ideal_nand.h"
#include "tests/cpp/contracts/nand_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Ideal, NandContract,
                               ::testing::Types<socpuppet::IdealNand>);
