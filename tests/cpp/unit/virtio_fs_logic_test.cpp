#include "socpuppet/core/virtio_fs_logic.h"

#include <cstddef>
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

// The file system device's request queue, with the driver's side and the
// device's side, and the device, whose answerer answers each request with
// "eggs:" and the request.
struct Rig {
  static constexpr Virtqueue::Layout kQueue{
      .desc = kMemory + 0x1000,
      .avail = kMemory + 0x2000,
      .used = kMemory + 0x3000,
      .size = 8,
  };

  Rig() {
    fs.SetAnswerer([this](std::span<const std::uint8_t> request) {
      asked.emplace_back(request.begin(), request.end());
      std::vector<std::uint8_t> answer = Bytes("eggs:");
      answer.insert(answer.end(), request.begin(), request.end());
      return answer;
    });
  }

  // Hands the device the chain that starts at descriptor 0 on `queue`.
  void HandOver(std::uint16_t queue) {
    driver.MakeAvailable(0);
    fs.Handle(queue, NextChain(ring), ring);
  }

  MemoryAt memory{kMemory};
  VirtqueueDriver driver{memory, kQueue, kMemory + 0x4000};
  Virtqueue ring{memory, kQueue};
  VirtioFsLogic fs;
  std::vector<std::vector<std::uint8_t>> asked;
};

TEST(WhenTheDriverSendsARequestInTwoPartsWithRoomForTheAnswerInTwo,
     TheAnswererIsAskedTheWholeRequestAndItsAnswerFillsTheRoom) {
  // FUSE's clients put a request's header and its body in a descriptor
  // each, and the answer's header and body the same way.
  Rig rig;
  rig.driver.Describe(0, 4, VirtqueueDriver::kNext, 1);
  rig.driver.Fill(0, Bytes("spam"));
  rig.driver.Describe(1, 2, VirtqueueDriver::kNext, 2);
  rig.driver.Fill(1, Bytes("!!"));
  rig.driver.Describe(2, 5, VirtqueueDriver::kWrite | VirtqueueDriver::kNext,
                      3);
  rig.driver.Describe(3, 16, VirtqueueDriver::kWrite);

  rig.HandOver(VirtioFsLogic::kRequestQueue);

  ASSERT_EQ(rig.asked.size(), 1U);
  EXPECT_EQ(rig.asked[0], Bytes("spam!!"));
  EXPECT_EQ(rig.driver.UsedAt(0).length, 11U);
  const std::vector<std::uint8_t> first = rig.driver.Contents(2, 5);
  const std::vector<std::uint8_t> second = rig.driver.Contents(3, 6);
  EXPECT_EQ(std::string(first.begin(), first.end()), "eggs:");
  EXPECT_EQ(std::string(second.begin(), second.end()), "spam!!");
}

TEST(WhenTheDriverSendsARequestThatHasNoAnswerOnTheHighPriorityQueue,
     TheAnswererIsAskedAndTheChainComesBackWithNothingWritten) {
  // FORGET goes on the high-priority queue, with no room for an answer.
  Rig rig;
  rig.driver.Describe(0, 4, VirtqueueDriver::kReadable);
  rig.driver.Fill(0, Bytes("spam"));

  rig.HandOver(VirtioFsLogic::kHighPriorityQueue);

  EXPECT_EQ(rig.asked.size(), 1U);
  EXPECT_EQ(rig.driver.UsedIndex(), 1);
  EXPECT_EQ(rig.driver.UsedAt(0).length, 0U);
}

TEST(WhenNothingAnswersTheDevice, ARequestComesBackWithNothingWritten) {
  Rig rig;
  rig.fs.SetAnswerer(nullptr);
  rig.driver.Describe(0, 4, VirtqueueDriver::kNext, 1);
  rig.driver.Fill(0, Bytes("spam"));
  rig.driver.Describe(1, 16, VirtqueueDriver::kWrite);

  rig.HandOver(VirtioFsLogic::kRequestQueue);

  EXPECT_EQ(rig.driver.UsedIndex(), 1);
  EXPECT_EQ(rig.driver.UsedAt(0).length, 0U);
}

TEST(WhenTheDriverReadsTheConfiguration,
     ItFindsTheTagPaddedToThirtySixBytesAndOneRequestQueue) {
  VirtioFsLogic fs;
  fs.SetTag("spam");

  const std::span<const std::uint8_t> config = fs.Config();

  ASSERT_EQ(config.size(), 40U);
  std::string tag(config.begin(), config.begin() + 36);
  EXPECT_EQ(tag, std::string("spam").append(32, '\0'));
  EXPECT_EQ(LoadLittleEndian<std::uint32_t>(config.subspan(36, 4)), 1U);
}

TEST(WhenTheShareIsNamedWithATagLongerThanTheConfigurationHolds,
     TheTagIsCutToFitAndTheQueueCountIsUntouched) {
  VirtioFsLogic fs;
  fs.SetTag(std::string(40, 's'));

  const std::span<const std::uint8_t> config = fs.Config();

  EXPECT_EQ(std::string(config.begin(), config.begin() + 36),
            std::string(36, 's'));
  EXPECT_EQ(LoadLittleEndian<std::uint32_t>(config.subspan(36, 4)), 1U);
}

TEST(WhenTheDriverLooksAtTheFileSystemDevice,
     ItIsKindTwentySixWithTwoQueuesAndNoFeatures) {
  VirtioFsLogic fs;

  EXPECT_EQ(fs.DeviceId(), 26U);
  EXPECT_EQ(fs.QueueCount(), 2);
  EXPECT_EQ(fs.Features(), 0U);
}

}  // namespace

}  // namespace socpuppet
