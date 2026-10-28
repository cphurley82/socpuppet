#include "socpuppet/core/spi_nor_chip.h"

#include <array>
#include <cstddef>
#include <cstdint>

namespace socpuppet {

namespace {

constexpr std::uint8_t kReadJedecId = 0x9F;

// Winbond's maker code, then the W25Q family, then the capacity, as the
// power of two of the size in bytes (0x18: 16 MiB).
constexpr std::array<std::uint8_t, 3> kJedecId{0xEF, 0x40, 0x18};

}  // namespace

SpiNorChip::SpiNorChip(std::size_t /*size*/) {}

void SpiNorChip::Select() { position_ = 0; }

std::uint8_t SpiNorChip::Transfer(std::uint8_t sent) {
  const std::size_t position = position_++;
  if (position == 0) {
    command_ = sent;
    return 0;
  }
  if (command_ == kReadJedecId && position <= kJedecId.size()) {
    return kJedecId[position - 1];
  }
  return 0;
}

void SpiNorChip::Deselect() {}

}  // namespace socpuppet
