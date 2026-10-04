#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace socpuppet {

// The bytes of a memory, with no simulator attached.
//
// read() and write() return false, and touch nothing, when the access does
// not fit inside the memory.
class MemoryStore {
 public:
  explicit MemoryStore(std::size_t size) : bytes_(size) {}

  bool read(std::size_t offset, std::span<std::uint8_t> out) const {
    if (!fits(offset, out.size())) return false;
    std::copy_n(bytes_.begin() + offset, out.size(), out.begin());
    return true;
  }

  bool write(std::size_t offset, std::span<const std::uint8_t> in) {
    if (!fits(offset, in.size())) return false;
    std::copy(in.begin(), in.end(), bytes_.begin() + offset);
    return true;
  }

 private:
  bool fits(std::size_t offset, std::size_t length) const {
    return offset <= bytes_.size() && length <= bytes_.size() - offset;
  }

  std::vector<std::uint8_t> bytes_;
};

}  // namespace socpuppet
