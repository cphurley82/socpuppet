#include "memory_contract.h"
#include "socpuppet/models/memory.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Ram, MemoryContract, ::testing::Types<socpuppet::Memory>);
