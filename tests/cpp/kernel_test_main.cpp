#include <iostream>
#include <string>
#include <string_view>

#include <gtest/gtest.h>

#include "socpuppet/platform/logging.h"
#include "tests/cpp/support/qbox_fates.h"
#include "tests/cpp/support/the_cpu.h"

// We provide main() ourselves. libsystemc carries its own main(), which
// expects the classic sc_main() entry point; defining ours first keeps the
// linker from pulling that one in.
//
// On QBox, a test the qbox_cpu does not pass (tests/cpp/support/
// qbox_fates.h) is not run. CTest runs one test a process, named by
// gtest's filter, and for that one the reason is printed after the mark
// CTest counts a skip by. A run of more is filtered.
//
// If setting up throws, the run ends with the exception's message, which is
// the outcome we want.
// NOLINTNEXTLINE(bugprone-exception-escape)
int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  if (TheCpu() == "qbox_cpu") {
    const std::string filter = GTEST_FLAG_GET(filter);
    const std::string_view reason = WhyQboxFails(filter);
    if (!reason.empty()) {
      std::cout << "[  SKIPPED ] " << filter << ", on QBox: " << reason << '\n';
      return 0;
    }
    // A run of many tests, by hand, leaves them all out.
    GTEST_FLAG_SET(filter, filter + (filter.find('-') == std::string::npos
                                         ? AllQboxFates()
                                         : ":" + AllQboxFates().substr(1)));
  }
  socpuppet::InitLogging(false);
  return RUN_ALL_TESTS();
}
