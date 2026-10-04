#ifndef SOCPUPPET_CORE_MEMORY_STORE_H_
#define SOCPUPPET_CORE_MEMORY_STORE_H_

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
    std::ranges::copy(std::span{bytes_}.subspan(offset, out.size()),
                      out.begin());
    return true;
  }

  bool write(std::size_t offset, std::span<const std::uint8_t> in) {
    if (!fits(offset, in.size())) return false;
    std::ranges::copy(in, std::span{bytes_}.subspan(offset).begin());
    return true;
  }

  // The whole memory as one block, for callers that are allowed to bypass
  // read() and write() (direct memory access).
  std::span<std::uint8_t> bytes() { return bytes_; }

 private:
  bool fits(std::size_t offset, std::size_t length) const {
    return offset <= bytes_.size() && length <= bytes_.size() - offset;
  }

  std::vector<std::uint8_t> bytes_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_MEMORY_STORE_H_
