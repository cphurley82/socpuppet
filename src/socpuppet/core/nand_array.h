#ifndef SOCPUPPET_CORE_NAND_ARRAY_H_
#define SOCPUPPET_CORE_NAND_ARRAY_H_

#include <algorithm>
#include <cstdint>
#include <span>
#include <unordered_map>
#include <vector>

#include "socpuppet/core/nand_geometry.h"

namespace socpuppet {

// How an operation on the array came out.
enum class NandResult {
  kDone,
  // There is no such block, or no such page in the block.
  kOutOfRange,
  // The data is not one page long.
  kWrongLength,
};

// The cells of a NAND flash chip, with no simulator in them: pages that
// are read and programmed whole, in blocks that are erased whole.
//
// It is an ideal chip. A page may be programmed again without erasing its
// block first, which no real NAND allows, and nothing wears out.
class NandArray {
 public:
  explicit NandArray(const NandGeometry& geometry) : geometry_(geometry) {}

  const NandGeometry& geometry() const { return geometry_; }

  // A page nothing was ever programmed into reads as all ones, which is
  // what an erased NAND cell holds.
  NandResult ReadPage(std::uint32_t block, std::uint32_t page,
                      std::span<std::uint8_t> out) const {
    if (!IsAPage(block, page)) return NandResult::kOutOfRange;
    if (out.size() != geometry_.page_size) return NandResult::kWrongLength;
    const std::vector<std::uint8_t>* programmed = Find(block, page);
    if (programmed == nullptr) {
      std::ranges::fill(out, kErased);
    } else {
      std::ranges::copy(*programmed, out.begin());
    }
    return NandResult::kDone;
  }

  NandResult ProgramPage(std::uint32_t block, std::uint32_t page,
                         std::span<const std::uint8_t> in) {
    if (!IsAPage(block, page)) return NandResult::kOutOfRange;
    if (in.size() != geometry_.page_size) return NandResult::kWrongLength;
    blocks_[block][page].assign(in.begin(), in.end());
    return NandResult::kDone;
  }

  NandResult EraseBlock(std::uint32_t block) {
    if (block >= geometry_.blocks) return NandResult::kOutOfRange;
    blocks_.erase(block);
    return NandResult::kDone;
  }

 private:
  static constexpr std::uint8_t kErased = 0xFF;

  bool IsAPage(std::uint32_t block, std::uint32_t page) const {
    return block < geometry_.blocks && page < geometry_.pages_per_block;
  }

  // What was programmed into a page, or nothing if nothing was.
  const std::vector<std::uint8_t>* Find(std::uint32_t block,
                                        std::uint32_t page) const {
    const auto pages = blocks_.find(block);
    if (pages == blocks_.end()) return nullptr;
    const auto programmed = pages->second.find(page);
    return programmed == pages->second.end() ? nullptr : &programmed->second;
  }

  NandGeometry geometry_;
  // The pages that hold something, by block and then by page. Only those
  // take any memory, so a chip may be far larger than the machine it is
  // simulated on, and erasing a block is forgetting it.
  std::unordered_map<
      std::uint32_t,
      std::unordered_map<std::uint32_t, std::vector<std::uint8_t>>>
      blocks_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NAND_ARRAY_H_
