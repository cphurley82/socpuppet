// The qbox_cpu: QBox's RISC-V CPU, which only a build with QBox has
// (SOCPUPPET_QBOX_DIR). What it does as a bus master is the contract's
// (contracts/bus_master_test.cpp); what is here is how it is asked for.

#include <stdexcept>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"

using ::testing::AllOf;
using ::testing::HasSubstr;
using ::testing::ThrowsMessage;

namespace {

#if !SOCPUPPET_HAS_QBOX

TEST(WhenTheBuildHasNoQbox, AQboxCpuIsRefusedAndTheErrorSaysHowToBuildOne) {
  socpuppet::Platform platform{socpuppet::BuiltinComponents()};

  EXPECT_THAT(
      [&] {
        platform.Add("cpu", "qbox_cpu", {{"xlen", 64}, {"reset_vector", 0}});
      },
      ThrowsMessage<std::invalid_argument>(AllOf(
          HasSubstr("tools/build_qbox.sh"), HasSubstr("SOCPUPPET_QBOX_DIR"))));
}

#endif

}  // namespace
