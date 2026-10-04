#include <gtest/gtest.h>
#include <systemc>

TEST(WhenASystemCKernelRunsInsideATest, SimulatedTimeAdvances) {
  sc_core::sc_start(10, sc_core::SC_NS);

  EXPECT_EQ(sc_core::sc_time_stamp(), sc_core::sc_time(10, sc_core::SC_NS));
}
