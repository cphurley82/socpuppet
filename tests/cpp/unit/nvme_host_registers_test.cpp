#include "socpuppet/core/nvme_host_registers.h"

#include <gtest/gtest.h>

namespace socpuppet {

// The doorbells start at 0x1000, four bytes apart (CAP.DSTRD is 0): a
// submission queue's tail, then its completion queue's head, queue after
// queue.
TEST(WhenAWriteLandsOnACompletionQueueHeadDoorbell, ItAcknowledgesCompletions) {
  EXPECT_TRUE(NvmeHostRegisters::IsCompletionHeadDoorbell(
      0x1004));  // the admin queue's
  EXPECT_TRUE(
      NvmeHostRegisters::IsCompletionHeadDoorbell(0x100C));  // I/O queue 1's
}

TEST(WhenAWriteLandsOnASubmissionQueueTailDoorbell,
     ItAcknowledgesNoCompletions) {
  EXPECT_FALSE(NvmeHostRegisters::IsCompletionHeadDoorbell(0x1000));
  EXPECT_FALSE(NvmeHostRegisters::IsCompletionHeadDoorbell(0x1008));
}

TEST(WhenAWriteLandsOnAControllerRegister, ItAcknowledgesNoCompletions) {
  EXPECT_FALSE(NvmeHostRegisters::IsCompletionHeadDoorbell(0x14));  // CC
}

}  // namespace socpuppet
