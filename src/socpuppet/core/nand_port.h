#ifndef SOCPUPPET_CORE_NAND_PORT_H_
#define SOCPUPPET_CORE_NAND_PORT_H_

#include <cstdint>
#include <optional>
#include <span>

#include "socpuppet/core/nand_array.h"

namespace socpuppet {

// A NAND flash chip, as the controller in front of it reaches it. A flash
// controller's logic is handed one of these, so that it can be tested with
// no simulator.
//
// Each operation returns false if the chip refused it: there is no such
// block or page, say.
class NandPort {
 public:
  virtual ~NandPort() = default;

  // What the chip is, or nothing if it would not say.
  virtual std::optional<NandGeometry> Geometry() = 0;
  virtual bool ReadPage(std::uint32_t block, std::uint32_t page,
                        std::span<std::uint8_t> out) = 0;
  virtual bool ProgramPage(std::uint32_t block, std::uint32_t page,
                           std::span<const std::uint8_t> in) = 0;
  virtual bool EraseBlock(std::uint32_t block) = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_NAND_PORT_H_
