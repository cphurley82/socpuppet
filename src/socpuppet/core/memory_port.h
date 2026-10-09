#ifndef SOCPUPPET_CORE_MEMORY_PORT_H_
#define SOCPUPPET_CORE_MEMORY_PORT_H_

#include <cstdint>
#include <span>

namespace socpuppet {

// Memory that a device reads and writes on its own initiative, by address:
// the host's, when an SSD does DMA (direct memory access), or the SSD's
// own buffer. A device's logic is handed one of these, so that it can be
// tested with no simulator and no bus.
//
// Each returns false if the access was not taken: nothing is at the
// address, say.
class MemoryPort {
 public:
  virtual ~MemoryPort() = default;
  virtual bool Read(std::uint64_t address, std::span<std::uint8_t> out) = 0;
  virtual bool Write(std::uint64_t address,
                     std::span<const std::uint8_t> in) = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_MEMORY_PORT_H_
