#ifndef SOCPUPPET_CORE_NAND_ARRAY_H_
#define SOCPUPPET_CORE_NAND_ARRAY_H_

#include <algorithm>
#include <cstdint>
#include <span>
#include <unordered_map>
#include <vector>

namespace socpuppet {

// How a NAND flash chip is laid out: blocks, each of so many pages, each of
// so many bytes. A page is what is read and programmed at a time, and a
// block is what is erased at a time.
struct NandGeometry {
  std::uint32_t page_size;
  std::uint32_t pages_per_block;
  std::uint32_t blocks;
};

// How an operation on the array came out.
enum class NandResult {
  kDone,
  // There is no such block, or no such page in the block.
  kOutOfRange,
};

// The cells of a NAND flash chip, with no simulator in them: pages that
// are read and programmed whole, in blocks that are erased whole.
class NandArray {
 public:
  explicit NandArray(const NandGeometry& geometry) : geometry_(geometry) {}

  const NandGeometry& geometry() const { return geometry_; }

  // A page nothing was ever programmed into reads as all ones, which is
  // what an erased NAND cell holds.
  NandResult ReadPage(std::uint32_t block, std::uint32_t page,
                      std::span<std::uint8_t> out) const {
    if (block >= geometry_.blocks) return NandResult::kOutOfRange;
    const auto programmed = pages_.find(Index(block, page));
    if (programmed == pages_.end()) {
      std::ranges::fill(out, kErased);
    } else {
      std::ranges::copy(programmed->second, out.begin());
    }
    return NandResult::kDone;
  }

  NandResult ProgramPage(std::uint32_t block, std::uint32_t page,
                         std::span<const std::uint8_t> in) {
    if (block >= geometry_.blocks) return NandResult::kOutOfRange;
    pages_[Index(block, page)].assign(in.begin(), in.end());
    return NandResult::kDone;
  }

  NandResult EraseBlock(std::uint32_t block) {
    if (block >= geometry_.blocks) return NandResult::kOutOfRange;
    for (std::uint32_t page = 0; page < geometry_.pages_per_block; ++page) {
      pages_.erase(Index(block, page));
    }
    return NandResult::kDone;
  }

 private:
  static constexpr std::uint8_t kErased = 0xFF;

  // A page's number, counting through the whole chip.
  std::uint64_t Index(std::uint32_t block, std::uint32_t page) const {
    return (std::uint64_t{block} * geometry_.pages_per_block) + page;
  }

  NandGeometry geometry_;
  // The pages that hold something, by their number. Only those take any
  // memory, so a chip may be far larger than the machine it is simulated on.
  std::unordered_map<std::uint64_t, std::vector<std::uint8_t>> pages_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NAND_ARRAY_H_
