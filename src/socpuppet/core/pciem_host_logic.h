#ifndef SOCPUPPET_CORE_PCIEM_HOST_LOGIC_H_
#define SOCPUPPET_CORE_PCIEM_HOST_LOGIC_H_

#include <cstdint>
#include <vector>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/pciem_device.h"

// What a PciemHost does, with no simulator attached: it turns the writes
// pciem posts on its ring into writes on the function's registers
// (pciem_device.h has what pciem plays and what it leaves to us).

namespace socpuppet {

// The bytes a host write puts on the bus, lowest first.
inline std::vector<std::uint8_t> BytesOf(const HostWrite& write) {
  const auto all = LittleEndianBytes<std::uint64_t>(write.data);
  return {all.begin(), all.begin() + write.size};
}

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_PCIEM_HOST_LOGIC_H_
