#include "socpuppet/models/machine_timer.h"

#include <gtest/gtest.h>

#include "tests/cpp/contracts/machine_timer_contract.h"

INSTANTIATE_TYPED_TEST_SUITE_P(MachineTimer, MachineTimerContract,
                               ::testing::Types<socpuppet::MachineTimer>);
