#include "socpuppet/core/nand_array.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <vector>

#include <gtest/gtest.h>

namespace socpuppet {

namespace {

// A small chip: 4 blocks of 8 pages, each page 16 bytes.
constexpr NandGeometry kSmall{
    .page_size = 16, .pages_per_block = 8, .blocks = 4};

// What the array holds in one page. The buffer does not start out as ones,
// so that a page the array leaves untouched is not taken for an erased one.
std::vector<std::uint8_t> PageAt(const NandArray& nand, std::uint32_t block,
                                 std::uint32_t page) {
  std::vector<std::uint8_t> data(nand.Geometry().page_size, 0xA5);
  EXPECT_EQ(nand.ReadPage(block, page, data), NandResult::kDone);
  return data;
}

// A page of data in which no two neighbouring bytes are the same.
std::vector<std::uint8_t> SomePage(std::uint8_t first_byte = 1) {
  std::vector<std::uint8_t> data(kSmall.page_size);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(first_byte + index);
  }
  return data;
}

// So many pages of data, page n starting at 16 * n, so that no two are
// alike.
std::vector<std::uint8_t> SomePages(std::uint8_t count) {
  std::vector<std::uint8_t> data;
  for (std::uint8_t page = 0; page < count; ++page) {
    const std::vector<std::uint8_t> one = SomePage(16 * page);
    data.insert(data.end(), one.begin(), one.end());
  }
  return data;
}

// How many bytes a chip holds.
constexpr std::size_t BytesIn(const NandGeometry& geometry) {
  return std::size_t{geometry.page_size} * geometry.pages_per_block *
         geometry.blocks;
}

}  // namespace

TEST(WhenAPageWasNeverProgrammed, ItReadsAsAllOnes) {
  const NandArray nand{kSmall};

  EXPECT_EQ(PageAt(nand, 2, 5), std::vector<std::uint8_t>(16, 0xFF));
}

TEST(WhenAPageIsProgrammed, ItReadsBackAsItWasProgrammed) {
  NandArray nand{kSmall};

  ASSERT_EQ(nand.ProgramPage(2, 5, SomePage()), NandResult::kDone);

  EXPECT_EQ(PageAt(nand, 2, 5), SomePage());
}

TEST(WhenAPageIsProgrammed, ThePagesAroundItStillReadAsAllOnes) {
  NandArray nand{kSmall};

  ASSERT_EQ(nand.ProgramPage(2, 5, SomePage()), NandResult::kDone);

  const std::vector<std::uint8_t> erased(kSmall.page_size, 0xFF);
  EXPECT_EQ(PageAt(nand, 2, 4), erased);
  EXPECT_EQ(PageAt(nand, 2, 6), erased);
  // The page with the same number in the blocks on either side.
  EXPECT_EQ(PageAt(nand, 1, 5), erased);
  EXPECT_EQ(PageAt(nand, 3, 5), erased);
}

TEST(WhenABlockIsErased, EveryPageOfItReadsAsAllOnes) {
  NandArray nand{kSmall};
  ASSERT_EQ(nand.ProgramPage(2, 0, SomePage()), NandResult::kDone);
  ASSERT_EQ(nand.ProgramPage(2, 7, SomePage()), NandResult::kDone);

  ASSERT_EQ(nand.EraseBlock(2), NandResult::kDone);

  const std::vector<std::uint8_t> erased(kSmall.page_size, 0xFF);
  EXPECT_EQ(PageAt(nand, 2, 0), erased);
  EXPECT_EQ(PageAt(nand, 2, 7), erased);
}

TEST(WhenABlockIsErased, TheBlocksAroundItKeepWhatTheyHold) {
  NandArray nand{kSmall};
  ASSERT_EQ(nand.ProgramPage(1, 7, SomePage(10)), NandResult::kDone);
  ASSERT_EQ(nand.ProgramPage(3, 0, SomePage(20)), NandResult::kDone);

  ASSERT_EQ(nand.EraseBlock(2), NandResult::kDone);

  EXPECT_EQ(PageAt(nand, 1, 7), SomePage(10));
  EXPECT_EQ(PageAt(nand, 3, 0), SomePage(20));
}

TEST(WhenABlockPastTheEndOfTheChipIsAskedFor, ReadingItIsRefused) {
  const NandArray nand{kSmall};
  std::vector<std::uint8_t> data(kSmall.page_size);

  EXPECT_EQ(nand.ReadPage(4, 0, data), NandResult::kOutOfRange);
}

TEST(WhenABlockPastTheEndOfTheChipIsAskedFor, ProgrammingItIsRefused) {
  NandArray nand{kSmall};

  EXPECT_EQ(nand.ProgramPage(4, 0, SomePage()), NandResult::kOutOfRange);
}

TEST(WhenABlockPastTheEndOfTheChipIsAskedFor, ErasingItIsRefused) {
  NandArray nand{kSmall};

  EXPECT_EQ(nand.EraseBlock(4), NandResult::kOutOfRange);
}

// Page 8 of block 0 would be the first page of block 1, if pages were
// simply counted through the chip.
TEST(WhenAPagePastTheEndOfItsBlockIsAskedFor, ReadingItIsRefused) {
  const NandArray nand{kSmall};
  std::vector<std::uint8_t> data(kSmall.page_size);

  EXPECT_EQ(nand.ReadPage(0, 8, data), NandResult::kOutOfRange);
}

TEST(WhenAPagePastTheEndOfItsBlockIsAskedFor, ProgrammingItIsRefused) {
  NandArray nand{kSmall};

  EXPECT_EQ(nand.ProgramPage(0, 8, SomePage()), NandResult::kOutOfRange);
  EXPECT_EQ(PageAt(nand, 1, 0),
            std::vector<std::uint8_t>(kSmall.page_size, 0xFF));
}

TEST(WhenTheDataIsNotOnePageLong, ReadingIsRefused) {
  const NandArray nand{kSmall};
  std::vector<std::uint8_t> too_short(kSmall.page_size - 1);
  std::vector<std::uint8_t> too_long(kSmall.page_size + 1);

  EXPECT_EQ(nand.ReadPage(0, 0, too_short), NandResult::kWrongLength);
  EXPECT_EQ(nand.ReadPage(0, 0, too_long), NandResult::kWrongLength);
}

TEST(WhenTheDataIsNotOnePageLong, ProgrammingIsRefused) {
  NandArray nand{kSmall};
  std::vector<std::uint8_t> too_short(kSmall.page_size - 1, 0x11);
  std::vector<std::uint8_t> too_long(kSmall.page_size + 1, 0x22);

  EXPECT_EQ(nand.ProgramPage(0, 0, too_short), NandResult::kWrongLength);
  EXPECT_EQ(nand.ProgramPage(0, 0, too_long), NandResult::kWrongLength);
  EXPECT_EQ(PageAt(nand, 0, 0),
            std::vector<std::uint8_t>(kSmall.page_size, 0xFF));
}

// What makes this array ideal. A real NAND cell can only be changed from
// one to zero by programming, so a page has to be erased, a whole block at
// a time, before it can hold something new.
TEST(WhenAPageIsProgrammedASecondTime, ItHoldsWhatWasProgrammedLast) {
  NandArray nand{kSmall};
  ASSERT_EQ(nand.ProgramPage(2, 5, SomePage(10)), NandResult::kDone);

  ASSERT_EQ(nand.ProgramPage(2, 5, SomePage(20)), NandResult::kDone);

  EXPECT_EQ(PageAt(nand, 2, 5), SomePage(20));
}

// 🧵 How Python programs a chip before a run, as a NAND programmer does a
// chip before it is soldered on: an image, laid over the pages in order.
TEST(WhenAnImageIsLoaded, ItsPagesAreTheArraysFirstInOrderAcrossBlocks) {
  NandArray nand{kSmall};
  const std::vector<std::uint8_t> image = SomePages(9);

  ASSERT_EQ(nand.Load(image), NandResult::kDone);

  EXPECT_EQ(PageAt(nand, 0, 0), SomePage(0));
  EXPECT_EQ(PageAt(nand, 0, 7), SomePage(16 * 7));
  // The ninth page is the first of the second block.
  EXPECT_EQ(PageAt(nand, 1, 0), SomePage(16 * 8));
}

TEST(WhenAnImageIsLoaded, APageItEndsPartWayThroughIsFilledOutWithOnes) {
  NandArray nand{kSmall};
  const std::vector<std::uint8_t> image(20, 0x00);

  ASSERT_EQ(nand.Load(image), NandResult::kDone);

  std::vector<std::uint8_t> second(kSmall.page_size, 0xFF);
  std::fill_n(second.begin(), 4, 0x00);
  EXPECT_EQ(PageAt(nand, 0, 1), second);
}

TEST(WhenAnImageLongerThanTheChipIsLoaded, ItIsRefusedWithNothingProgrammed) {
  NandArray nand{kSmall};
  const std::vector<std::uint8_t> image(BytesIn(kSmall) + 1, 0x00);

  EXPECT_EQ(nand.Load(image), NandResult::kOutOfRange);

  EXPECT_EQ(PageAt(nand, 0, 0),
            std::vector<std::uint8_t>(kSmall.page_size, 0xFF));
}

TEST(WhenTheContentsAreRead, TheyAreEveryPageInOrderAndErasedOnesAreOnes) {
  NandArray nand{kSmall};
  ASSERT_EQ(nand.ProgramPage(1, 2, SomePage()), NandResult::kDone);

  const std::vector<std::uint8_t> contents = nand.Contents();

  std::vector<std::uint8_t> expected(BytesIn(kSmall), 0xFF);
  const std::size_t block_1_page_2 =
      std::size_t{kSmall.page_size} * ((1 * kSmall.pages_per_block) + 2);
  std::ranges::copy(SomePage(), expected.begin() + block_1_page_2);
  EXPECT_EQ(contents, expected);
}

}  // namespace socpuppet
