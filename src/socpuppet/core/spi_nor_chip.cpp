#include "socpuppet/core/spi_nor_chip.h"

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>

namespace socpuppet {

namespace {

constexpr std::uint8_t kReadJedecId = 0x9F;

// The JEDEC id: Winbond's maker code, then the W25Q family, then the
// capacity, as the power of two of the size in bytes (0x18: 16 MiB).
std::array<std::uint8_t, 3> JedecId(std::size_t size) {
  return {0xEF, 0x40, static_cast<std::uint8_t>(std::bit_width(size) - 1)};
}

}  // namespace

SpiNorChip::SpiNorChip(std::size_t size) : size_(size) {}

void SpiNorChip::Select() { position_ = 0; }

std::uint8_t SpiNorChip::Transfer(std::uint8_t sent) {
  const std::size_t position = position_++;
  if (position == 0) {
    command_ = sent;
    return 0;
  }
  if (command_ == kReadJedecId) {
    const auto id = JedecId(size_);
    if (position <= id.size()) return id[position - 1];
  }
  return 0;
}

void SpiNorChip::Deselect() {}

}  // namespace socpuppet
