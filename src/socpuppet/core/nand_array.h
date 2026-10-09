#ifndef SOCPUPPET_CORE_NAND_ARRAY_H_
#define SOCPUPPET_CORE_NAND_ARRAY_H_

#include <algorithm>
#include <cstdint>
#include <span>

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
};

// The cells of a NAND flash chip, with no simulator in them: pages that
// are read and programmed whole, in blocks that are erased whole.
class NandArray {
 public:
  explicit NandArray(const NandGeometry& geometry) : geometry_(geometry) {}

  const NandGeometry& geometry() const { return geometry_; }

  // A page nothing was ever programmed into reads as all ones, which is
  // what an erased NAND cell holds.
  NandResult ReadPage(std::uint32_t /*block*/, std::uint32_t /*page*/,
                      std::span<std::uint8_t> out) const {
    std::ranges::fill(out, kErased);
    return NandResult::kDone;
  }

 private:
  static constexpr std::uint8_t kErased = 0xFF;

  NandGeometry geometry_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NAND_ARRAY_H_
