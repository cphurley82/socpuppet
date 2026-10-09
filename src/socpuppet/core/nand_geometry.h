#ifndef SOCPUPPET_CORE_NAND_GEOMETRY_H_
#define SOCPUPPET_CORE_NAND_GEOMETRY_H_

#include <cstdint>

namespace socpuppet {

// How a NAND flash chip is laid out: blocks, each of so many pages, each of
// so many bytes. A page is what is read and programmed at a time, and a
// block is what is erased at a time.
struct NandGeometry {
  std::uint32_t page_size;
  std::uint32_t pages_per_block;
  std::uint32_t blocks;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NAND_GEOMETRY_H_
