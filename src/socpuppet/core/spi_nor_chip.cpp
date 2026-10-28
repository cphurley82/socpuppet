#include "socpuppet/core/spi_nor_chip.h"

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <span>

namespace socpuppet {

namespace {

// The commands, by the first byte of a frame. Winbond's datasheet has the
// same names.
constexpr std::uint8_t kRead = 0x03;
constexpr std::uint8_t kWriteDisable = 0x04;
constexpr std::uint8_t kReadStatus = 0x05;
constexpr std::uint8_t kWriteEnable = 0x06;
constexpr std::uint8_t kFastRead = 0x0B;
constexpr std::uint8_t kReadJedecId = 0x9F;

// Status register 1's write enable latch: writes are enabled.
constexpr std::uint8_t kWriteEnableLatch = 1 << 1;

// What an erased byte of NOR flash reads as: every bit a one.
constexpr std::uint8_t kErased = 0xFF;

// How many bytes an address is sent in.
constexpr std::size_t kAddressBytes = 3;

// The JEDEC id: Winbond's maker code, then the W25Q family, then the
// capacity, as the power of two of the size in bytes (0x18: 16 MiB).
std::array<std::uint8_t, 3> JedecId(std::size_t size) {
  return {0xEF, 0x40, static_cast<std::uint8_t>(std::bit_width(size) - 1)};
}

}  // namespace

SpiNorChip::SpiNorChip(std::size_t size) : bytes_(size, kErased) {}

void SpiNorChip::Select() {
  position_ = 0;
  address_ = 0;
}

std::uint8_t SpiNorChip::Transfer(std::uint8_t sent) {
  const std::size_t position = position_++;
  if (position == 0) {
    command_ = sent;
    // 🎓 A real chip sets or clears the latch when the select goes high
    // after the command; this one does it as the command arrives, as
    // QEMU's m25p80 does, which no controller can tell apart.
    if (command_ == kWriteEnable) write_enable_latch_ = true;
    if (command_ == kWriteDisable) write_enable_latch_ = false;
    return 0;
  }
  if (command_ == kReadStatus)
    return write_enable_latch_ ? kWriteEnableLatch : 0;
  if (command_ == kReadJedecId) {
    const auto id = JedecId(bytes_.size());
    if (position <= id.size()) return id[position - 1];
  }
  if (command_ == kRead || command_ == kFastRead) {
    if (position <= kAddressBytes) {
      address_ = (address_ << 8) | sent;
      return 0;
    }
    // A fast read's eight dummy clocks, which a controller that moves
    // whole bytes sends as one byte.
    if (command_ == kFastRead && position == kAddressBytes + 1) return 0;
    // An address wraps at the chip's end, as it does on the real one: the
    // chip ignores the bits above its size, which is a power of two.
    return bytes_[address_++ & (bytes_.size() - 1)];
  }
  return 0;
}

void SpiNorChip::Deselect() {}

std::span<std::uint8_t> SpiNorChip::Bytes() { return bytes_; }

}  // namespace socpuppet
