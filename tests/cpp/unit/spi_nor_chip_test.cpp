#include "socpuppet/core/spi_nor_chip.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

namespace socpuppet {

namespace {

using ::testing::_;
using ::testing::ElementsAre;

constexpr std::size_t kEightMebibytes = 8 * 1024 * 1024;
constexpr std::size_t kSixteenMebibytes = 16 * 1024 * 1024;

// One frame: chip select down, `sent` out a byte at a time, chip select
// up. Returns what came back for each byte sent.
std::vector<std::uint8_t> Frame(SpiDevice& chip,
                                std::initializer_list<std::uint8_t> sent) {
  std::vector<std::uint8_t> received;
  chip.Select();
  for (const std::uint8_t byte : sent) {
    received.push_back(chip.Transfer(byte));
  }
  chip.Deselect();
  return received;
}

// Whether the chip's status register says writes are enabled. 🎓 Bit 1 of
// status register 1, which RDSR (0x05) reads, is the write enable latch.
bool WriteEnableLatch(SpiDevice& chip) {
  constexpr std::uint8_t kWriteEnableLatch = 1 << 1;
  const std::vector<std::uint8_t> received = Frame(chip, {0x05, 0});
  return (received.back() & kWriteEnableLatch) != 0;
}

}  // namespace

TEST(WhenASixteenMebibyteChipIsAskedForItsJedecId, ItAnswersEf4018) {
  SpiNorChip chip{kSixteenMebibytes};

  EXPECT_THAT(Frame(chip, {0x9F, 0, 0, 0}), ElementsAre(_, 0xEF, 0x40, 0x18));
}

TEST(WhenAnEightMebibyteChipIsAskedForItsJedecId, ItsCapacityByteIs17) {
  SpiNorChip chip{kEightMebibytes};

  EXPECT_THAT(Frame(chip, {0x9F, 0, 0, 0}), ElementsAre(_, _, _, 0x17));
}

TEST(WhenAnErasedChipIsRead, EveryByteReadsFf) {
  SpiNorChip chip{kSixteenMebibytes};

  EXPECT_THAT(Frame(chip, {0x03, 0x12, 0x34, 0x56, 0, 0, 0}),
              ElementsAre(_, _, _, _, 0xFF, 0xFF, 0xFF));
}

TEST(WhenAChipIsReadWhereBytesWerePutIn, ItAnswersThoseBytes) {
  SpiNorChip chip{kSixteenMebibytes};
  constexpr std::array<std::uint8_t, 2> kPutIn{0xCA, 0xFE};
  std::ranges::copy(kPutIn, chip.Bytes().subspan(0x12'3456).begin());

  EXPECT_THAT(Frame(chip, {0x03, 0x12, 0x34, 0x56, 0, 0}),
              ElementsAre(_, _, _, _, 0xCA, 0xFE));
}

TEST(WhenAnEightMebibyteChipIsSentAnAddressPastItsEnd,
     ItReadsFromTheAddressLessItsSize) {
  SpiNorChip chip{kEightMebibytes};
  constexpr std::array<std::uint8_t, 2> kPutIn{0xCA, 0xFE};
  std::ranges::copy(kPutIn, chip.Bytes().subspan(0x12'3456).begin());

  EXPECT_THAT(Frame(chip, {0x03, 0x92, 0x34, 0x56, 0, 0}),
              ElementsAre(_, _, _, _, 0xCA, 0xFE));
}

// 🎓 A fast read waits eight clocks after its address before it answers,
// time the chip needs at a high clock rate. A controller that moves whole
// bytes sends them as one byte the chip ignores.
TEST(WhenAChipIsFastReadWhereBytesWerePutIn,
     ItAnswersThoseBytesAfterADummyByte) {
  SpiNorChip chip{kSixteenMebibytes};
  constexpr std::array<std::uint8_t, 2> kPutIn{0xCA, 0xFE};
  std::ranges::copy(kPutIn, chip.Bytes().subspan(0x12'3456).begin());

  EXPECT_THAT(Frame(chip, {0x0B, 0x12, 0x34, 0x56, 0, 0, 0}),
              ElementsAre(_, _, _, _, _, 0xCA, 0xFE));
}

TEST(WhenWritesToAChipHaveBeenEnabled, ItsStatusShowsTheWriteEnableLatch) {
  SpiNorChip chip{kSixteenMebibytes};
  Frame(chip, {0x06});

  EXPECT_TRUE(WriteEnableLatch(chip));
}

TEST(WhenWritesToAChipHaveBeenEnabledAndThenDisabled,
     ItsStatusShowsTheWriteEnableLatchClear) {
  SpiNorChip chip{kSixteenMebibytes};
  Frame(chip, {0x06});
  Frame(chip, {0x04});

  EXPECT_FALSE(WriteEnableLatch(chip));
}

TEST(WhenAnErasedChipIsProgrammedWithWritesEnabled, ItReadsWhatWasProgrammed) {
  SpiNorChip chip{kSixteenMebibytes};
  Frame(chip, {0x06});

  Frame(chip, {0x02, 0x12, 0x34, 0x56, 0xCA, 0xFE});

  EXPECT_THAT(Frame(chip, {0x03, 0x12, 0x34, 0x56, 0, 0}),
              ElementsAre(_, _, _, _, 0xCA, 0xFE));
}

TEST(WhenAnErasedChipIsProgrammedWithWritesDisabled, ItStillReadsAsErased) {
  SpiNorChip chip{kSixteenMebibytes};

  Frame(chip, {0x02, 0x12, 0x34, 0x56, 0xCA, 0xFE});

  EXPECT_THAT(Frame(chip, {0x03, 0x12, 0x34, 0x56, 0, 0}),
              ElementsAre(_, _, _, _, 0xFF, 0xFF));
}

// 🎓 Programming can only turn ones into zeros. Only an erase turns a zero
// back into a one.
TEST(WhenAChipIsProgrammedOverBytesItHolds, OnlyTheBitsBothHaveAsOnesStayOnes) {
  SpiNorChip chip{kSixteenMebibytes};
  chip.Bytes()[0x12'3456] = 0x0F;
  Frame(chip, {0x06});

  Frame(chip, {0x02, 0x12, 0x34, 0x56, 0x3C});

  EXPECT_THAT(Frame(chip, {0x03, 0x12, 0x34, 0x56, 0}),
              ElementsAre(_, _, _, _, 0x0C));
}

}  // namespace socpuppet
