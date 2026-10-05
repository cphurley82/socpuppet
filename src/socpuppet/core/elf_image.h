#ifndef SOCPUPPET_CORE_ELF_IMAGE_H_
#define SOCPUPPET_CORE_ELF_IMAGE_H_

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace socpuppet {

// What is in an ELF file that matters for putting a program into memory.
// (ELF is the format a linker writes: the program's bytes in segments, each
// with the address it belongs at.)
struct ElfImage {
  // A run of bytes and the physical address it is to be loaded at.
  //
  // Only the bytes that are in the file. A segment may ask for more memory
  // than it has bytes, to be filled with zeros (a program's `.bss`). That
  // tail is not represented: memory starts out zeroed, and a program clears
  // its own.
  struct Segment {
    std::uint64_t address;
    std::vector<std::byte> bytes;
  };

  // The word size the program was built for, in bits: 32 or 64.
  unsigned xlen = 0;
  // The address of the first instruction to execute.
  std::uint64_t entry = 0;
  // The loadable segments that have bytes in the file.
  std::vector<Segment> segments;
};

// Reads the ELF file at `path`. Throws std::invalid_argument, naming the
// file, if it cannot be read as one.
ElfImage ReadElfImage(const std::string& path);

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_ELF_IMAGE_H_
