#ifndef SOCPUPPET_CORE_LITTLE_ENDIAN_H_
#define SOCPUPPET_CORE_LITTLE_ENDIAN_H_

#include <array>
#include <concepts>
#include <cstddef>
#include <cstdint>
#include <span>

namespace socpuppet {

// A number as bytes, least significant byte first (little-endian). That is
// how a number lies in memory on the buses here, in PCI configuration
// space and in everything NVMe defines. Going by way of these, and not by
// copying a variable's own bytes, gives the same answer whatever machine
// the simulator is built on.

// Writes `value` into the first bytes of `bytes`, as many as it has.
template <std::unsigned_integral Value>
constexpr void StoreLittleEndian(Value value, std::span<std::uint8_t> bytes) {
  for (std::size_t index = 0; index < sizeof(Value); ++index) {
    bytes[index] = static_cast<std::uint8_t>(value >> (8 * index));
  }
}

// The number in the first bytes of `bytes`, as many as it has.
template <std::unsigned_integral Value>
constexpr Value LoadLittleEndian(std::span<const std::uint8_t> bytes) {
  Value value = 0;
  for (std::size_t index = 0; index < sizeof(Value); ++index) {
    value = static_cast<Value>(value | Value{bytes[index]} << (8 * index));
  }
  return value;
}

// The bytes of `value`.
template <std::unsigned_integral Value>
constexpr std::array<std::uint8_t, sizeof(Value)> LittleEndianBytes(
    Value value) {
  std::array<std::uint8_t, sizeof(Value)> bytes{};
  StoreLittleEndian(value, bytes);
  return bytes;
}

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_LITTLE_ENDIAN_H_
