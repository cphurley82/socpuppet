#ifndef SOCPUPPET_CORE_PCIEM_DEVICE_H_
#define SOCPUPPET_CORE_PCIEM_DEVICE_H_

#include <cstdint>

// 🐧 A PCIe device on this machine's own bus, played by this program
// through pciem's /dev/pciem (https://github.com/cakehonolulu/pciem).
//
// pciem's kernel side plays the device's configuration space and its MSI-X
// table, and puts each base address register (BAR) in memory set aside at
// boot. A host write to BAR0 lands in that memory (pciem's shadow write)
// and is posted on a ring for us. A host read never reaches us: it reads
// the memory, so what the host should read has to be put there first.

namespace socpuppet {

// One write the host made to a BAR, as pciem posted it.
struct HostWrite {
  std::uint32_t bar = 0;
  std::uint64_t offset = 0;
  std::uint32_t size = 0;  // bytes: 1, 2, 4 or 8
  std::uint64_t data = 0;  // only the low `size` bytes mean anything
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_PCIEM_DEVICE_H_
