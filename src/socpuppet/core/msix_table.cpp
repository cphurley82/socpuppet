#include "socpuppet/core/msix_table.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

namespace {

// An entry of the table: the address in two halves, the data, and a word
// whose lowest bit masks the vector.
constexpr std::size_t kEntrySize = 16;
constexpr std::size_t kEntryData = 8;
constexpr std::size_t kEntryControl = 12;
constexpr std::uint8_t kEntryMasked = 1U << 0;

}  // namespace

MsixTable::MsixTable(std::size_t vectors)
    : entries_(vectors * kEntrySize), pending_(vectors) {
  for (std::size_t vector = 0; vector < vectors; ++vector) {
    entries_[(vector * kEntrySize) + kEntryControl] = kEntryMasked;
  }
}

void MsixTable::Read(std::uint64_t offset, std::span<std::uint8_t> out) const {
  std::ranges::copy(std::span{entries_}.subspan(offset, out.size()),
                    out.begin());
}

void MsixTable::Write(std::uint64_t offset, std::span<const std::uint8_t> in) {
  std::ranges::copy(in, std::span{entries_}.subspan(offset).begin());
}

void MsixTable::ReadPendingBits(std::uint64_t offset,
                                std::span<std::uint8_t> out) const {
  for (std::size_t index = 0; index < out.size(); ++index) {
    std::uint8_t byte = 0;
    for (std::size_t bit = 0; bit < 8; ++bit) {
      const std::size_t vector = ((offset + index) * 8) + bit;
      if (vector < pending_.size() && pending_[vector]) {
        byte = static_cast<std::uint8_t>(byte | (1U << bit));
      }
    }
    out[index] = byte;
  }
}

bool MsixTable::IsMasked(std::size_t vector) const {
  return (entries_[(vector * kEntrySize) + kEntryControl] & kEntryMasked) != 0;
}

MsixTable::Message MsixTable::MessageOf(std::size_t vector) const {
  const std::span entry =
      std::span{entries_}.subspan(vector * kEntrySize, kEntrySize);
  return {.address = LoadLittleEndian<std::uint64_t>(entry),
          .data = LoadLittleEndian<std::uint32_t>(entry.subspan(kEntryData))};
}

}  // namespace socpuppet
