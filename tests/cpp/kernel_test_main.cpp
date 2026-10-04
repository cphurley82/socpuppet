#include <gtest/gtest.h>

#include "socpuppet/platform/logging.h"

// We provide main() ourselves. libsystemc carries its own main(), which
// expects the classic sc_main() entry point; defining ours first keeps the
// linker from pulling that one in.
//
// If setting up throws, the run ends with the exception's message, which is
// the outcome we want.
// NOLINTNEXTLINE(bugprone-exception-escape)
int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  socpuppet::InitLogging(false);
  return RUN_ALL_TESTS();
}
