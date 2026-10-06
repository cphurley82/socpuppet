#ifndef SOCPUPPET_CORE_PRP_H_
#define SOCPUPPET_CORE_PRP_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <vector>

namespace socpuppet {

// The size of a page of the host's memory, as NVMe counts in them: 4 KiB,
// the smallest the specification allows, and the only one the controller
// here offers.
inline constexpr std::uint64_t kPrpPageSize = 4096;

// One run of bytes in the host's memory.
struct HostExtent {
  std::uint64_t address = 0;
  std::size_t length = 0;
  bool operator==(const HostExtent&) const = default;
};

// Reads the 64-bit entry at the given address in the host's memory.
// (Spelled with a trailing return type because cpplint takes the usual
// spelling for a cast.)
using ReadPrpEntry = std::function<auto(std::uint64_t)->std::uint64_t>;

// Where a command's data is in the host's memory, piece by piece and in
// order.
//
// An NVMe command says where its data is with physical region pages
// (PRPs): the addresses of the memory pages that hold it, which need not
// be next to each other. A command has room for two entries.
//   - The first is where the data starts, which may be part way into a
//     page. The data runs from there to the end of that page.
//   - If what is left fits in one more page, the second entry is that page.
//   - If not, the second entry is the address of a list in the host's
//     memory: one 64-bit entry for each page after the first.
//   - A list that reaches the end of its own page with more pages still to
//     name carries on elsewhere: its last entry is the address of the rest
//     of the list.
//
// `read_entry` is how the list is read.
inline std::vector<HostExtent> PrpExtents(std::uint64_t prp1,
                                          std::uint64_t prp2,
                                          std::size_t length,
                                          const ReadPrpEntry& read_entry) {
  constexpr std::uint64_t kEntrySize = sizeof(std::uint64_t);
  const std::size_t in_first_page =
      std::min<std::uint64_t>(length, kPrpPageSize - (prp1 % kPrpPageSize));
  std::vector<HostExtent> extents{{.address = prp1, .length = in_first_page}};
  std::size_t remaining = length - in_first_page;
  if (remaining == 0) return extents;
  if (remaining <= kPrpPageSize) {
    extents.push_back({.address = prp2, .length = remaining});
    return extents;
  }
  std::uint64_t entry = prp2;
  while (remaining > 0) {
    const bool last_of_its_page = (entry + kEntrySize) % kPrpPageSize == 0;
    if (last_of_its_page && remaining > kPrpPageSize) {
      entry = read_entry(entry);
      continue;
    }
    const std::size_t piece = std::min<std::uint64_t>(remaining, kPrpPageSize);
    extents.push_back({.address = read_entry(entry), .length = piece});
    remaining -= piece;
    entry += kEntrySize;
  }
  return extents;
}

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_PRP_H_
