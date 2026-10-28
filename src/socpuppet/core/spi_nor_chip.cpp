#include "socpuppet/core/spi_nor_chip.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <span>

namespace socpuppet {

namespace {

// The commands, by the first byte of a frame. Winbond's datasheet has the
// same names.
constexpr std::uint8_t kPageProgram = 0x02;
constexpr std::uint8_t kRead = 0x03;
constexpr std::uint8_t kWriteDisable = 0x04;
constexpr std::uint8_t kReadStatus = 0x05;
constexpr std::uint8_t kWriteEnable = 0x06;
constexpr std::uint8_t kFastRead = 0x0B;
constexpr std::uint8_t kSectorErase = 0x20;
constexpr std::uint8_t kBlockErase32 = 0x52;
constexpr std::uint8_t kReadJedecId = 0x9F;

// Status register 1's write enable latch: writes are enabled.
constexpr std::uint8_t kWriteEnableLatch = 1 << 1;

// What an erased byte of NOR flash reads as: every bit a one.
constexpr std::uint8_t kErased = 0xFF;

// How many bytes an address is sent in.
constexpr std::size_t kAddressBytes = 3;

// How many bytes a command erases, the aligned block its address is in, or
// zero for a command that erases nothing.
std::size_t ErasedBytes(std::uint8_t command) {
  switch (command) {
    case kSectorErase:
      return 4 * 1024;
    case kBlockErase32:
      return 32 * 1024;
    default:
      return 0;
  }
}

// Whether a command is followed by an address.
bool TakesAnAddress(std::uint8_t command) {
  return command == kPageProgram || command == kRead || command == kFastRead ||
         ErasedBytes(command) != 0;
}

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
  if (TakesAnAddress(command_) && position <= kAddressBytes) {
    address_ = (address_ << 8) | sent;
    // 🎓 A real chip erases when the select goes high after the address,
    // and not at all if more bytes come first; this one erases as the
    // address's last byte arrives, as QEMU's m25p80 does. Neither Linux's
    // driver nor Zephyr's sends more, so none can tell.
    if (position == kAddressBytes && ErasedBytes(command_) != 0) {
      EraseBlock(ErasedBytes(command_));
    }
    return 0;
  }
  if (command_ == kPageProgram) {
    // 🎓 A real W25Q wraps a program within its 256-byte page; this one
    // carries on to the next, as QEMU's m25p80 does. Neither Linux's
    // driver nor Zephyr's sends a program across a page, so none can tell.
    //
    // Programming can only turn ones into zeros, so a program ANDs what is
    // sent into what the chip holds; only an erase brings the ones back.
    if (write_enable_latch_) NextByte() &= sent;
    return 0;
  }
  if (command_ == kRead || command_ == kFastRead) {
    // A fast read's eight dummy clocks, which a controller that moves
    // whole bytes sends as one byte.
    if (command_ == kFastRead && position == kAddressBytes + 1) return 0;
    return NextByte();
  }
  return 0;
}

void SpiNorChip::Deselect() {}

void SpiNorChip::EraseBlock(std::size_t bytes) {
  // A block's size is a power of two, as the chip's is, so the block an
  // address is in starts where the address's low bits are cleared.
  const std::size_t start = ChipAddress() & ~(bytes - 1);
  std::ranges::fill(std::span(bytes_).subspan(start, bytes), kErased);
}

std::size_t SpiNorChip::ChipAddress() const {
  // An address wraps at the chip's end, as it does on the real one: the
  // chip ignores the bits above its size, which is a power of two.
  return address_ & (bytes_.size() - 1);
}

std::uint8_t& SpiNorChip::NextByte() {
  std::uint8_t& byte = bytes_[ChipAddress()];
  ++address_;
  return byte;
}

std::span<std::uint8_t> SpiNorChip::Bytes() { return bytes_; }

}  // namespace socpuppet
