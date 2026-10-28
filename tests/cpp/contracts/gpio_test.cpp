#include "socpuppet/models/gpio.h"

#include <gtest/gtest.h>

#include "tests/cpp/contracts/gpio_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Gpio, GpioContract,
                               ::testing::Types<socpuppet::Gpio>);
