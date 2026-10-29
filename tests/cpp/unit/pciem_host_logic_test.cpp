#include "socpuppet/core/pciem_host_logic.h"

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "socpuppet/core/pciem_device.h"

namespace socpuppet {

using ::testing::ElementsAre;

TEST(WhenAHostWriteIsFourBytesWide, OnlyItsLowFourBytesGoOnTheBus) {
  // pciem may leave what was in its slot's high bytes before.
  const HostWrite write{.size = 4, .data = 0xDEAD'BEEF'0403'0201};

  EXPECT_THAT(BytesOf(write), ElementsAre(0x01, 0x02, 0x03, 0x04));
}

TEST(WhenAHostWriteIsEightBytesWide, AllEightGoOnTheBusLowestFirst) {
  const HostWrite write{
      .offset = 0x28,
      .size = 8,
      .data = 0x0123'4567'89AB'CDEF,
  };

  EXPECT_THAT(BytesOf(write),
              ElementsAre(0xEF, 0xCD, 0xAB, 0x89, 0x67, 0x45, 0x23, 0x01));
}

}  // namespace socpuppet
