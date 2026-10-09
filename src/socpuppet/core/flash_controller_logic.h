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
  // and touches nothing, if there is no register to take the access.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out);
  // The same read as a debugger makes it, which nothing may notice: the
  // chip is not asked what it is, so until something else has asked, the
  // geometry registers are seen as zeros.
  bool PeekRegister(std::uint64_t offset, std::span<std::uint8_t> out) const;
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in);

  // Does what the command register was last told, if it has not been done
  // yet. Returns whether there was anything to do.
  bool CarryOut();

  // Whether the controller is asking for its CPU's attention.
  bool Interrupting() const { return (status_ & interrupt_enable_) != 0; }

 private:
  // Carries a command out, and returns whether it could be.
  bool Do(std::uint32_t command);

  // What the chip is, all zeros if it will not say. The chip is asked the
  // first time anything needs to know, and its answer is kept.
  NandGeometry Geometry();

  NandPort& nand_;
  MemoryPort& local_memory_;
  std::optional<NandGeometry> geometry_;
  // What the command register was told and has not done yet, or zero.
  std::uint32_t command_ = 0;
  std::uint32_t status_ = 0;
  // Which bits of the status interrupt the CPU while they are set.
  std::uint32_t interrupt_enable_ = 0;
  // Which page of the chip, and where it is in the SSD's own memory.
  std::uint32_t block_ = 0;
  std::uint32_t page_ = 0;
  std::uint32_t local_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_FLASH_CONTROLLER_LOGIC_H_
