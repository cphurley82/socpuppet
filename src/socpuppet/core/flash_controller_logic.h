#ifndef SOCPUPPET_CORE_FLASH_CONTROLLER_LOGIC_H_
#define SOCPUPPET_CORE_FLASH_CONTROLLER_LOGIC_H_

#include <cstdint>
#include <optional>
#include <span>

#include "socpuppet/core/memory_port.h"
#include "socpuppet/core/nand_port.h"

namespace socpuppet {

// What a flash controller does, with no simulator attached: the registers
// the SSD's CPU talks to, and the page it moves between the NAND chip and
// the SSD's own memory when told to.
class FlashControllerLogic {
 public:
  FlashControllerLogic(NandPort& nand, MemoryPort& local_memory);

  // Reads and writes of the register block, by the CPU. Each returns false,
  // and touches nothing, if the access is refused: there is no register
  // there, it is not 32 bits wide, a register that only says something is
  // written to, or the command register is told something it does not
  // know, or anything at all while the last command is not yet done.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const;
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in);

  // Does what the command register was last told, if it has not been done
  // yet. Returns whether there was anything to do.
  bool CarryOut();

  // Whether the controller is asking for its CPU's attention.
  bool Interrupting() const { return (status_ & interrupt_enable_) != 0; }

 private:
  // Carries a command out, and returns whether it could be.
  bool Do(std::uint32_t command);

  NandPort& nand_;
  MemoryPort& local_memory_;
  // What the chip is, once it has been told to say (the identify
  // command), and has said.
  std::optional<NandGeometry> geometry_;
  // What the command register was told and has not done yet, or zero.
  std::uint32_t command_ = 0;
  std::uint32_t status_ = 0;
  // Which bits of the status interrupt the CPU while they are set.
  std::uint32_t interrupt_enable_ = 0;
  // Which page of the chip, and where it is in the SSD's own memory.
  std::uint32_t block_ = 0;
  std::uint32_t page_ = 0;
  std::uint32_t local_address_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_FLASH_CONTROLLER_LOGIC_H_
