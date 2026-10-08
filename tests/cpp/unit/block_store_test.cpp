#include "socpuppet/core/block_store.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <vector>

#include <gtest/gtest.h>

namespace socpuppet {

namespace {

constexpr std::size_t kBlockSize = BlockStore::kBlockSize;

// `blocks` blocks of data in which no two neighbouring bytes are the same
// and no block is the same as the next.
std::vector<std::uint8_t> SomeBlocks(std::size_t blocks) {
  std::vector<std::uint8_t> data(blocks * kBlockSize);
  for (std::size_t index = 0; index < data.size(); ++index) {
    data[index] = static_cast<std::uint8_t>(index + (index / kBlockSize));
  }
  return data;
}

// What the store holds from block `first` on, `blocks` blocks of it. The
// buffer does not start out as zeros, so that a block the store leaves
// untouched is not taken for one that reads as zeros.
std::vector<std::uint8_t> ReadFrom(const BlockStore& store, std::uint64_t first,
                                   std::size_t blocks) {
  std::vector<std::uint8_t> data(blocks * kBlockSize, 0xA5);
  store.Read(first, data);
  return data;
}

}  // namespace

TEST(WhenABlockWasNeverWritten, ItReadsAsZeros) {
  const RamBlockStore store{/*blocks=*/16};

  EXPECT_EQ(ReadFrom(store, 3, 1), std::vector<std::uint8_t>(kBlockSize, 0));
}

TEST(WhenBlocksAreWritten, TheyReadBackAsTheyWereWritten) {
  RamBlockStore store{/*blocks=*/16};
  const std::vector<std::uint8_t> written = SomeBlocks(2);

  store.Write(5, written);

  EXPECT_EQ(ReadFrom(store, 5, 2), written);
}

TEST(WhenBlocksAreWritten, TheirNeighboursStillReadAsZeros) {
  RamBlockStore store{/*blocks=*/16};

  store.Write(5, SomeBlocks(2));

  EXPECT_EQ(ReadFrom(store, 4, 1), std::vector<std::uint8_t>(kBlockSize, 0));
  EXPECT_EQ(ReadFrom(store, 7, 1), std::vector<std::uint8_t>(kBlockSize, 0));
}

// The store keeps what was written in pieces of many blocks each. A run of
// blocks long enough crosses from one piece into the next wherever the
// pieces happen to end.
TEST(WhenALongRunOfBlocksIsWritten, ItReadsBackWhole) {
  RamBlockStore store{/*blocks=*/4096};
  const std::vector<std::uint8_t> written = SomeBlocks(1000);

  store.Write(100, written);

  EXPECT_EQ(ReadFrom(store, 100, 1000), written);
}

TEST(WhenAStoreIsAskedHowManyBlocksItHolds, ItSaysWhatItWasMadeWith) {
  const RamBlockStore store{/*blocks=*/2048};

  EXPECT_EQ(store.Blocks(), 2048U);
}

// A terabyte: more than the machine has, and nothing like what the store
// takes, because only what has been written is kept.
TEST(WhenADriveIsLargerThanTheMachinesMemory, ItsLastBlockCanBeWritten) {
  constexpr std::uint64_t kBlocks = std::uint64_t{1} << 31;
  RamBlockStore store{kBlocks};
  const std::vector<std::uint8_t> written = SomeBlocks(1);

  store.Write(kBlocks - 1, written);

  EXPECT_EQ(ReadFrom(store, kBlocks - 1, 1), written);
}

}  // namespace socpuppet
