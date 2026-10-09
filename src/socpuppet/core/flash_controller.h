#ifndef SOCPUPPET_CORE_FLASH_CONTROLLER_H_
#define SOCPUPPET_CORE_FLASH_CONTROLLER_H_

#include <cstdint>
#include <span>

#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/nand_port.h"

namespace socpuppet {

// What a flash controller does, with no simulator attached: the registers
// the SSD's CPU talks to, and the page it moves between the NAND chip and
// the SSD's own memory when told to.
class FlashController {
 public:
  FlashController(NandPort& nand, MemoryPort& local_memory);

  // Reads and writes of the register block, by the CPU. Each returns false,
  // and touches nothing, if there is no register to take the access.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out);
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in);

  // Does what the command register was last told, if it has not been done
  // yet. Returns whether there was anything to do.
  bool CarryOut();

 private:
  // Carries a command out, and returns whether it could be.
  bool Do(std::uint32_t command);

  NandPort& nand_;
  MemoryPort& local_memory_;
  // What the command register was told and has not done yet, or zero.
  std::uint32_t command_ = 0;
  std::uint32_t status_ = 0;
  // Which page of the chip, and where it is in the SSD's own memory.
  std::uint32_t block_ = 0;
  std::uint32_t page_ = 0;
  std::uint32_t local_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_FLASH_CONTROLLER_H_
