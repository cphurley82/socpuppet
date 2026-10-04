#include <gtest/gtest.h>

// We provide main() ourselves. libsystemc carries its own main(), which
// expects the classic sc_main() entry point; defining ours first keeps the
// linker from pulling that one in.
int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
