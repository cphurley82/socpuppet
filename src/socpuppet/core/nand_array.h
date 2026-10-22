#ifndef SOCPUPPET_CORE_NAND_ARRAY_H_
#define SOCPUPPET_CORE_NAND_ARRAY_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>
#include <unordered_map>
#include <vector>

#include "socpuppet/core/nand_geometry.h"

namespace socpuppet {

// How an operation on the array came out.
enum class NandResult {
  kDone,
  // There is no such block, no such page in the block, or an image runs
  // past the last page.
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

  const NandGeometry& Geometry() const { return geometry_; }

  // How many bytes the chip holds.
  std::size_t Size() const {
    return std::size_t{geometry_.page_size} * geometry_.pages_per_block *
           geometry_.blocks;
  }

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

  // Programs `image` over the pages in order, from the first page of the
  // first block, as a NAND programmer does a chip before it is soldered
  // on. A page the image ends part way through is filled out with ones,
  // as erased. An image longer than the chip is refused, with nothing
  // programmed.
  NandResult Load(std::span<const std::uint8_t> image) {
    if (image.size() > Size()) return NandResult::kOutOfRange;
    std::vector<std::uint8_t> data(geometry_.page_size);
    for (std::size_t page = 0; page * data.size() < image.size(); ++page) {
      const std::size_t at = page * data.size();
      const auto piece =
          image.subspan(at, std::min(data.size(), image.size() - at));
      std::ranges::fill(std::ranges::copy(piece, data.begin()).out, data.end(),
                        kErased);
      ProgramPage(static_cast<std::uint32_t>(page / geometry_.pages_per_block),
                  static_cast<std::uint32_t>(page % geometry_.pages_per_block),
                  data);
    }
    return NandResult::kDone;
  }

  // Every page of the chip, in order, the erased ones all ones.
  std::vector<std::uint8_t> Contents() const {
    std::vector<std::uint8_t> contents(Size());
    const std::span<std::uint8_t> all{contents};
    for (std::uint32_t block = 0; block < geometry_.blocks; ++block) {
      for (std::uint32_t page = 0; page < geometry_.pages_per_block; ++page) {
        const std::size_t at =
            (std::size_t{block} * geometry_.pages_per_block + page) *
            geometry_.page_size;
        ReadPage(block, page, all.subspan(at, geometry_.page_size));
      }
    }
    return contents;
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
