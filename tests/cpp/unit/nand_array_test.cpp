#include "socpuppet/core/nand_array.h"

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

}  // namespace socpuppet
