#include "socpuppet/models/memory.h"

#include "memory_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Ram, MemoryContract,
                               ::testing::Types<socpuppet::Memory>);
