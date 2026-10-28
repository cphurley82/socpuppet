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

}  // namespace socpuppet
