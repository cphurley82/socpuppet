#ifndef TESTS_CPP_SUPPORT_MEMORY_AT_H_
#define TESTS_CPP_SUPPORT_MEMORY_AT_H_

#include <cstddef>
#include <cstdint>
#include <span>

#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/memory_store.h"

// A memory of `size` bytes at address `base`, for tests of a device that
// reaches the driver's memory through a MemoryPort. An access below `base`
// or past the end fails, as one to nothing on a bus would.
class MemoryAt : public socpuppet::MemoryPort {
 public:
  static constexpr std::size_t kDefaultSize = 0x1'0000;

  explicit MemoryAt(std::uint64_t base, std::size_t size = kDefaultSize)
      : base_(base), store_(size) {}

  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return address >= base_ && store_.Read(address - base_, out);
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return address >= base_ && store_.Write(address - base_, in);
  }

 private:
  std::uint64_t base_;
  socpuppet::MemoryStore store_;
};

#endif  // TESTS_CPP_SUPPORT_MEMORY_AT_H_
