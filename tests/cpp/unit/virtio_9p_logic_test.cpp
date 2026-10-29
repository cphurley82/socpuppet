#include "socpuppet/core/virtio_9p_logic.h"

#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/virtqueue.h"
#include "tests/cpp/support/memory_at.h"
#include "tests/cpp/support/virtqueue_driver.h"

namespace socpuppet {

namespace {

constexpr std::uint64_t kMemory = 0x8000'0000;

std::vector<std::uint8_t> Bytes(std::string_view text) {
  return {text.begin(), text.end()};
}

// The 9p device's request queue, with the driver's side and the device's
// side, and the device, whose answerer answers each message with "eggs:"
// and the message.
struct Rig {
  static constexpr Virtqueue::Layout kQueue{
      .desc = kMemory + 0x1000,
      .avail = kMemory + 0x2000,
      .used = kMemory + 0x3000,
      .size = 8,
  };

  Rig() {
    ninep.SetAnswerer([this](std::span<const std::uint8_t> message) {
      asked.emplace_back(message.begin(), message.end());
      std::vector<std::uint8_t> answer = Bytes("eggs:");
      answer.insert(answer.end(), message.begin(), message.end());
      return answer;
    });
  }

  // Hands the device the chain that starts at descriptor 0.
  void HandOver() {
    driver.MakeAvailable(0);
    ninep.Handle(Virtio9pLogic::kRequestQueue, NextChain(ring), ring);
  }

  MemoryAt memory{kMemory};
  VirtqueueDriver driver{memory, kQueue, kMemory + 0x4000};
  Virtqueue ring{memory, kQueue};
  Virtio9pLogic ninep;
  std::vector<std::vector<std::uint8_t>> asked;
};

TEST(WhenTheDriverSendsAMessageInTwoPartsWithRoomForTheAnswerInTwo,
     TheAnswererIsAskedTheWholeMessageAndItsAnswerFillsTheRoom) {
  // 🎓 Linux's client puts a large write's header in one buffer and its
  // data in the pages after it, and a large read's answer the same way.
  Rig rig;
  rig.driver.Describe(0, 4, VirtqueueDriver::kNext, 1);
  rig.driver.Fill(0, Bytes("spam"));
  rig.driver.Describe(1, 2, VirtqueueDriver::kNext, 2);
  rig.driver.Fill(1, Bytes("!!"));
  rig.driver.Describe(2, 5, VirtqueueDriver::kWrite | VirtqueueDriver::kNext,
                      3);
  rig.driver.Describe(3, 16, VirtqueueDriver::kWrite);

  rig.HandOver();

  ASSERT_EQ(rig.asked.size(), 1U);
  EXPECT_EQ(rig.asked[0], Bytes("spam!!"));
  EXPECT_EQ(rig.driver.UsedAt(0).length, 11U);
  const std::vector<std::uint8_t> first = rig.driver.Contents(2, 5);
  const std::vector<std::uint8_t> second = rig.driver.Contents(3, 6);
  EXPECT_EQ(std::string(first.begin(), first.end()), "eggs:");
  EXPECT_EQ(std::string(second.begin(), second.end()), "spam!!");
}

TEST(WhenNothingAnswersThe9pDevice, AMessageComesBackWithNothingWritten) {
  Rig rig;
  rig.ninep.SetAnswerer(nullptr);
  rig.driver.Describe(0, 4, VirtqueueDriver::kNext, 1);
  rig.driver.Fill(0, Bytes("spam"));
  rig.driver.Describe(1, 16, VirtqueueDriver::kWrite);

  rig.HandOver();

  EXPECT_EQ(rig.driver.UsedIndex(), 1);
  EXPECT_EQ(rig.driver.UsedAt(0).length, 0U);
}

TEST(WhenTheDriverReadsThe9pConfiguration, ItFindsTheTagsLengthAndThenTheTag) {
  Virtio9pLogic ninep;
  ninep.SetTag("spam");

  const std::span<const std::uint8_t> config = ninep.Config();

  ASSERT_EQ(config.size(), 6U);
  EXPECT_EQ(LoadLittleEndian<std::uint16_t>(config.first(2)), 4U);
  EXPECT_EQ(std::string(config.begin() + 2, config.end()), "spam");
}

TEST(WhenTheDriverLooksAtThe9pDevice,
     ItIsKindNineWithOneQueueAndOffersItsMountTag) {
  // 🎓 Linux's driver will not take a 9p device that has no tag to mount
  // it by, which the feature says it has.
  Virtio9pLogic ninep;

  EXPECT_EQ(ninep.DeviceId(), 9U);
  EXPECT_EQ(ninep.QueueCount(), 1);
  EXPECT_EQ(ninep.Features(), 1U << 0U);
}

}  // namespace

}  // namespace socpuppet
