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
  std::vector<std::uint8_t> data(nand.geometry().page_size, 0xA5);
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

}  // namespace socpuppet
