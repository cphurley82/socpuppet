#include "socpuppet/core/flash_controller_logic.h"

#include <cstddef>
#include <vector>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/regs/flash_controller.h"

namespace socpuppet {

namespace {

// Each register is 32 bits wide. Where each one is, and what the command
// register can be told, are the register map's names for them
// (regs/flash_controller.rdl), which the driver and the docs go by as well.
constexpr std::size_t kRegisterBytes = 4;

// Whether the command register can be told `value`.
bool IsACommand(std::uint32_t value) {
  switch (value) {
    case FLASH_CONTROLLER_COMMAND_READ_PAGE:
    case FLASH_CONTROLLER_COMMAND_PROGRAM_PAGE:
    case FLASH_CONTROLLER_COMMAND_ERASE_BLOCK:
    case FLASH_CONTROLLER_COMMAND_IDENTIFY:
      return true;
    default:
      return false;
  }
}

}  // namespace

FlashControllerLogic::FlashControllerLogic(NandPort& nand,
                                           MemoryPort& local_memory)
    : nand_(nand), local_memory_(local_memory) {}

bool FlashControllerLogic::ReadRegister(std::uint64_t offset,
                                        std::span<std::uint8_t> out) const {
  if (out.size() != kRegisterBytes) return false;
  const NandGeometry geometry = geometry_.value_or(NandGeometry{});
  switch (offset) {
    case FLASH_CONTROLLER_COMMAND:
      StoreLittleEndian(std::uint32_t{0}, out);
      break;
    case FLASH_CONTROLLER_STATUS:
      StoreLittleEndian(status_.Status(), out);
      break;
    case FLASH_CONTROLLER_INTERRUPT_ENABLE:
      StoreLittleEndian(status_.InterruptEnable(), out);
      break;
    case FLASH_CONTROLLER_BLOCK:
      StoreLittleEndian(block_, out);
      break;
    case FLASH_CONTROLLER_PAGE:
      StoreLittleEndian(page_, out);
      break;
    case FLASH_CONTROLLER_LOCAL_ADDRESS:
      StoreLittleEndian(local_address_, out);
      break;
    case FLASH_CONTROLLER_PAGE_SIZE:
      StoreLittleEndian(geometry.page_size, out);
      break;
    case FLASH_CONTROLLER_PAGES_PER_BLOCK:
      StoreLittleEndian(geometry.pages_per_block, out);
      break;
    case FLASH_CONTROLLER_BLOCKS:
      StoreLittleEndian(geometry.blocks, out);
      break;
    default:
      return false;
  }
  return true;
}

bool FlashControllerLogic::WriteRegister(std::uint64_t offset,
                                         std::span<const std::uint8_t> in) {
  if (in.size() != kRegisterBytes) return false;
  const auto value = LoadLittleEndian<std::uint32_t>(in);
  switch (offset) {
    case FLASH_CONTROLLER_COMMAND:
      if (status_.Busy() || !IsACommand(value)) return false;
      job_ = Job{.command = value,
                 .block = block_,
                 .page = page_,
                 .local_address = local_address_};
      status_.Start();
      break;
    case FLASH_CONTROLLER_STATUS:
      status_.WriteStatus(value);
      break;
    case FLASH_CONTROLLER_INTERRUPT_ENABLE:
      status_.WriteInterruptEnable(value);
      break;
    case FLASH_CONTROLLER_BLOCK:
      block_ = value;
      break;
    case FLASH_CONTROLLER_PAGE:
      page_ = value;
      break;
    case FLASH_CONTROLLER_LOCAL_ADDRESS:
      local_address_ = value;
      break;
    default:
      return false;
  }
  return true;
}

bool FlashControllerLogic::CarryOut() {
  if (!status_.Busy()) return false;
  status_.Finish(Do(job_));
  return true;
}

bool FlashControllerLogic::Do(const Job& job) {
  switch (job.command) {
    case FLASH_CONTROLLER_COMMAND_READ_PAGE: {
      if (!geometry_) return false;
      std::vector<std::uint8_t> page(geometry_->page_size);
      return nand_.ReadPage(job.block, job.page, page) &&
             local_memory_.Write(job.local_address, page);
    }
    case FLASH_CONTROLLER_COMMAND_PROGRAM_PAGE: {
      if (!geometry_) return false;
      std::vector<std::uint8_t> page(geometry_->page_size);
      return local_memory_.Read(job.local_address, page) &&
             nand_.ProgramPage(job.block, job.page, page);
    }
    case FLASH_CONTROLLER_COMMAND_ERASE_BLOCK:
      return nand_.EraseBlock(job.block);
    case FLASH_CONTROLLER_COMMAND_IDENTIFY:
      geometry_ = nand_.Geometry();
      return geometry_.has_value();
    default:
      return false;
  }
}

}  // namespace socpuppet
