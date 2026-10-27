#include "socpuppet/models/iommu.h"

#include <gtest/gtest.h>

#include "tests/cpp/contracts/iommu_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Iommu, IommuContract,
                               ::testing::Types<socpuppet::Iommu>);
