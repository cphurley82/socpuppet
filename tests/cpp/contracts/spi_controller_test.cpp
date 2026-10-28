#include "socpuppet/models/spi_controller.h"

#include <gtest/gtest.h>

#include "tests/cpp/contracts/spi_controller_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(SpiController, SpiControllerContract,
                               ::testing::Types<socpuppet::SpiController>);
