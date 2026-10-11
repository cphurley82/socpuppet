#include "socpuppet/models/watchdog.h"

#include <gtest/gtest.h>

#include "tests/cpp/contracts/watchdog_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(Watchdog, WatchdogContract,
                               ::testing::Types<socpuppet::Watchdog>);
