#include "socpuppet/core/spi_nor_chip.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <format>
#include <initializer_list>
#include <span>
#include <string>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

namespace socpuppet {

namespace {

using ::testing::_;
using ::testing::Each;
using ::testing::ElementsAre;

// A chip smaller than a 32 KiB or 64 KiB block, the size of a 4 KiB sector.
constexpr std::size_t kFourKibibytes = std::size_t{4} * 1024;
// A small chip, for a test that looks at every byte, but bigger than the
// largest block an erase can take, so a chip erase shows it reached past
// one.
constexpr std::size_t kOneHundredTwentyEightKibibytes = std::size_t{128} * 1024;
constexpr std::size_t kEightMebibytes = std::size_t{8} * 1024 * 1024;
constexpr std::size_t kSixteenMebibytes = std::size_t{16} * 1024 * 1024;

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
  constexpr std::uint8_t kWriteEnableLatch = 1U << 1U;
  const std::vector<std::uint8_t> received = Frame(chip, {0x05, 0});
  return (received.back() & kWriteEnableLatch) != 0;
}

// The frame of a command that takes a three-byte address and nothing else.
void SendWithAddress(SpiDevice& chip, std::uint8_t command,
                     std::size_t address) {
  Frame(chip, {
                  command,
                  static_cast<std::uint8_t>(address >> 16U),
                  static_cast<std::uint8_t>(address >> 8U),
                  static_cast<std::uint8_t>(address),
              });
}

// An erase command and the size of the block it erases.
struct Erase {
  std::uint8_t command;
  std::size_t block;
};

// Each erase that takes an address, and the size of the block it erases.
constexpr std::array<Erase, 3> kBlockErases{
    Erase{.command = 0x20, .block = std::size_t{4} * 1024},
    Erase{.command = 0x52, .block = std::size_t{32} * 1024},
    Erase{.command = 0xD8, .block = std::size_t{64} * 1024},
};

// A row of kBlockErases by its command and its block: Command20Erases4KiB.
std::string BlockEraseName(const ::testing::TestParamInfo<Erase>& row) {
  return std::format("Command{:02X}Erases{}KiB", row.param.command,
                     row.param.block / 1024);
}

class WhenAChipIsErasedWithWritesEnabledAtAnAddressInsideABlock
    : public ::testing::TestWithParam<Erase> {};

class WhenAChipIsErasedWithWritesDisabledAtAnAddressInsideABlock
    : public ::testing::TestWithParam<Erase> {};

// Chip erase has two codes, and a chip answers either.
constexpr std::array<std::uint8_t, 2> kChipErases{0xC7, 0x60};

// A row of kChipErases by its command: CommandC7.
std::string ChipEraseName(const ::testing::TestParamInfo<std::uint8_t>& row) {
  return std::format("Command{:02X}", row.param);
}

class WhenAChipIsErasedWholeWithWritesEnabled
    : public ::testing::TestWithParam<std::uint8_t> {};

class WhenAChipIsErasedWholeWithWritesDisabled
    : public ::testing::TestWithParam<std::uint8_t> {};

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

TEST_P(WhenAChipIsErasedWithWritesEnabledAtAnAddressInsideABlock,
       TheWholeBlockReadsAsErasedAndNothingEitherSide) {
  const Erase erase = GetParam();
  SpiNorChip chip{kSixteenMebibytes};
  // Three blocks of zeros, and the address in the middle one.
  const std::span<std::uint8_t> blocks = chip.Bytes().first(3 * erase.block);
  std::ranges::fill(blocks, 0x00);
  const std::size_t address = erase.block + 0x123;
  Frame(chip, {0x06});

  SendWithAddress(chip, erase.command, address);

  EXPECT_THAT(blocks.first(erase.block), Each(0x00));
  EXPECT_THAT(blocks.subspan(erase.block, erase.block), Each(0xFF));
  EXPECT_THAT(blocks.last(erase.block), Each(0x00));
}

INSTANTIATE_TEST_SUITE_P(
    EachEraseCommand, WhenAChipIsErasedWithWritesEnabledAtAnAddressInsideABlock,
    ::testing::ValuesIn(kBlockErases), BlockEraseName);

TEST_P(WhenAChipIsErasedWithWritesDisabledAtAnAddressInsideABlock,
       TheBlockKeepsWhatItHolds) {
  const Erase erase = GetParam();
  SpiNorChip chip{kSixteenMebibytes};
  const std::span<std::uint8_t> block =
      chip.Bytes().subspan(erase.block, erase.block);
  std::ranges::fill(block, 0x00);

  SendWithAddress(chip, erase.command, erase.block + 0x123);

  EXPECT_THAT(block, Each(0x00));
}

INSTANTIATE_TEST_SUITE_P(
    EachEraseCommand,
    WhenAChipIsErasedWithWritesDisabledAtAnAddressInsideABlock,
    ::testing::ValuesIn(kBlockErases), BlockEraseName);

TEST_P(WhenAChipIsErasedWholeWithWritesEnabled, EveryByteReadsAsErased) {
  SpiNorChip chip{kOneHundredTwentyEightKibibytes};
  std::ranges::fill(chip.Bytes(), 0x00);
  Frame(chip, {0x06});

  Frame(chip, {GetParam()});

  EXPECT_THAT(chip.Bytes(), Each(0xFF));
}

INSTANTIATE_TEST_SUITE_P(EachChipEraseCommand,
                         WhenAChipIsErasedWholeWithWritesEnabled,
                         ::testing::ValuesIn(kChipErases), ChipEraseName);

TEST_P(WhenAChipIsErasedWholeWithWritesDisabled, ItKeepsWhatItHolds) {
  SpiNorChip chip{kOneHundredTwentyEightKibibytes};
  std::ranges::fill(chip.Bytes(), 0x00);

  Frame(chip, {GetParam()});

  EXPECT_THAT(chip.Bytes(), Each(0x00));
}

INSTANTIATE_TEST_SUITE_P(EachChipEraseCommand,
                         WhenAChipIsErasedWholeWithWritesDisabled,
                         ::testing::ValuesIn(kChipErases), ChipEraseName);

// A chip smaller than the block an erase takes, as a test's flash may be.
// No W25Q part is, so the datasheet does not say; erasing the chip whole
// is what the address's wrap at the chip's end suggests.
TEST(WhenAChipSmallerThanABlockIsErasedAsABlock, ItIsErasedWhole) {
  SpiNorChip chip{kFourKibibytes};
  std::ranges::fill(chip.Bytes(), 0x00);
  Frame(chip, {0x06});

  SendWithAddress(chip, 0xD8, 0);

  EXPECT_THAT(chip.Bytes(), Each(0xFF));
}

}  // namespace socpuppet
