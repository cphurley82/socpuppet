#include "socpuppet/core/nvme_controller.h"

#include <array>
#include <cstdint>
#include <span>

#include <gtest/gtest.h>

namespace socpuppet {

// The controller registers are the first 4 KiB of the register block, and
// the doorbells follow them. The first doorbell is the admin submission
// queue's.
constexpr std::uint64_t kAdminSubmissionDoorbell = 0x1000;

// A host with no memory, for tests in which the controller never looks.
class NoHostMemory : public MemoryPort {
  bool Read(std::uint64_t, std::span<std::uint8_t>) override { return true; }
  bool Write(std::uint64_t, std::span<const std::uint8_t>) override {
    return true;
  }
};

// An enabled controller whose admin queues have four entries each.
// AQA, at offset 0x24, holds both sizes, counted from zero. CC, the
// configuration, is at 0x14 with its enable bit lowest.
void EnableWithFourEntryAdminQueues(NvmeController& controller) {
  controller.WriteRegister(0x24, std::array<std::uint8_t, 4>{3, 0, 3, 0});
  controller.WriteRegister(0x14, std::array<std::uint8_t, 4>{1, 0, 0, 0});
}

// 512 TiB of drive: the controller keeps only what has been written.
TEST(WhenADriveIsFarLargerThanTheMachinesMemory, AControllerForItIsStillMade) {
  NoHostMemory memory;

  EXPECT_NO_THROW((NvmeController{memory, /*blocks=*/std::uint64_t{1} << 40,
                                  /*vectors=*/1}));
}

TEST(WhenTheHostReadsADoorbell, TheReadIsRefused) {
  NoHostMemory memory;
  const NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  std::array<std::uint8_t, 4> data{};

  EXPECT_FALSE(controller.ReadRegister(kAdminSubmissionDoorbell, data));
}

TEST(WhenARegisterReadRunsOnFromTheControllerRegistersIntoTheDoorbells,
     ItIsRefused) {
  NoHostMemory memory;
  const NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  std::array<std::uint8_t, 8> data{};

  EXPECT_FALSE(controller.ReadRegister(kAdminSubmissionDoorbell - 4, data));
}

TEST(WhenARegisterWriteRunsOnFromTheControllerRegistersIntoTheDoorbells,
     ItIsRefused) {
  NoHostMemory memory;
  NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  const std::array<std::uint8_t, 8> data{};

  EXPECT_FALSE(controller.WriteRegister(kAdminSubmissionDoorbell - 4, data));
}

TEST(WhenADoorbellWriteIsNot32BitsWide, ItIsRefused) {
  NoHostMemory memory;
  NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  const std::array<std::uint8_t, 8> data{};

  EXPECT_FALSE(controller.WriteRegister(kAdminSubmissionDoorbell, data));
}

TEST(WhenTheHostRingsTheDoorbellOfAQueueThatDoesNotExist, TheWriteIsRefused) {
  // Doorbells are 4 << CAP.DSTRD bytes apart. This controller reports a
  // stride of 0, so each queue pair takes 8 bytes and queue 1's doorbells
  // start 8 bytes on.
  //
  // Refusing the write is this model's rule. The specification has a real
  // controller accept it and report the mistake to the host later, as an
  // asynchronous event, which this model does not have.
  constexpr std::uint64_t kQueueOneSubmissionDoorbell =
      kAdminSubmissionDoorbell + 8;
  NoHostMemory memory;
  NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  EnableWithFourEntryAdminQueues(controller);
  const std::array<std::uint8_t, 4> data{};

  EXPECT_FALSE(controller.WriteRegister(kQueueOneSubmissionDoorbell, data));
}

TEST(WhenTheHostResetsTheController, TheAdminQueueRegistersKeepTheirValues) {
  // AQA (how long the admin queues are) is at offset 0x24, ASQ and ACQ
  // (where they are) at 0x28 and 0x30, and CC, the configuration, at 0x14
  // with its enable bit lowest.
  constexpr std::uint64_t kConfiguration = 0x14;
  constexpr std::uint64_t kAdminQueueAttributes = 0x24;
  constexpr std::uint64_t kAdminSubmissionQueue = 0x28;
  constexpr std::uint64_t kAdminCompletionQueue = 0x30;
  const std::array<std::uint8_t, 4> sizes{0x03, 0x00, 0x07, 0x00};
  const std::array<std::uint8_t, 4> submissions{0x00, 0x10, 0x00, 0x80};
  const std::array<std::uint8_t, 4> completions{0x00, 0x20, 0x00, 0x80};
  const std::array<std::uint8_t, 4> enabled{1, 0, 0, 0};
  const std::array<std::uint8_t, 4> disabled{0, 0, 0, 0};
  NoHostMemory memory;
  NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  controller.WriteRegister(kAdminQueueAttributes, sizes);
  controller.WriteRegister(kAdminSubmissionQueue, submissions);
  controller.WriteRegister(kAdminCompletionQueue, completions);
  controller.WriteRegister(kConfiguration, enabled);

  controller.WriteRegister(kConfiguration, disabled);

  std::array<std::uint8_t, 4> sizes_after{};
  std::array<std::uint8_t, 4> submissions_after{};
  std::array<std::uint8_t, 4> completions_after{};
  controller.ReadRegister(kAdminQueueAttributes, sizes_after);
  controller.ReadRegister(kAdminSubmissionQueue, submissions_after);
  controller.ReadRegister(kAdminCompletionQueue, completions_after);
  EXPECT_EQ(sizes_after, sizes);
  EXPECT_EQ(submissions_after, submissions);
  EXPECT_EQ(completions_after, completions);
}

TEST(WhenTheHostRingsADoorbellWithASlotPastTheEndOfTheQueue,
     TheWriteIsRefused) {
  NoHostMemory memory;
  NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  EnableWithFourEntryAdminQueues(controller);
  // The queue's slots are 0 to 3.
  const std::array<std::uint8_t, 4> slot_four{4, 0, 0, 0};

  EXPECT_FALSE(controller.WriteRegister(kAdminSubmissionDoorbell, slot_four));
}

TEST(WhenTheHostRingsADoorbellWhileTheControllerIsDisabled, TheWriteIsRefused) {
  // Slot 0 is a slot of every queue, so the only reason to refuse it is
  // that the admin queue is not there until the controller is enabled.
  NoHostMemory memory;
  NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  const std::array<std::uint8_t, 4> slot_zero{};

  EXPECT_FALSE(controller.WriteRegister(kAdminSubmissionDoorbell, slot_zero));
}

TEST(WhenTheHostWritesBetweenTwoDoorbells, TheWriteIsRefused) {
  NoHostMemory memory;
  NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  EnableWithFourEntryAdminQueues(controller);
  const std::array<std::uint8_t, 4> slot_one{1, 0, 0, 0};

  EXPECT_FALSE(
      controller.WriteRegister(kAdminSubmissionDoorbell + 2, slot_one));
}

TEST(WhenTheHostRingsADoorbellFarPastTheLastQueueTheControllerHas,
     TheWriteIsRefused) {
  // Queue 1000, which is far more queues than the controller has.
  NoHostMemory memory;
  NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  EnableWithFourEntryAdminQueues(controller);
  const std::array<std::uint8_t, 4> slot_zero{};

  EXPECT_FALSE(controller.WriteRegister(
      kAdminSubmissionDoorbell + (std::uint64_t{8} * 1000), slot_zero));
}

TEST(WhenTheHostRingsTheCompletionDoorbellOfAQueueThatDoesNotExist,
     TheWriteIsRefused) {
  // Queue 1's completion doorbell is the fourth doorbell.
  NoHostMemory memory;
  NvmeController controller{memory, /*blocks=*/0, /*vectors=*/1};
  EnableWithFourEntryAdminQueues(controller);
  const std::array<std::uint8_t, 4> slot_zero{};

  EXPECT_FALSE(
      controller.WriteRegister(kAdminSubmissionDoorbell + 12, slot_zero));
}

}  // namespace socpuppet
