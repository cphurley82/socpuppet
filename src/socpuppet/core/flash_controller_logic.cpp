#include "socpuppet/core/flash_controller_logic.h"

#include <cstddef>
#include <vector>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

namespace {

// Where the registers are. Each is 32 bits wide.
constexpr std::size_t kRegisterBytes = 4;
constexpr std::uint64_t kCommandRegister = 0x00;
constexpr std::uint64_t kStatusRegister = 0x04;
constexpr std::uint64_t kInterruptEnableRegister = 0x08;
constexpr std::uint64_t kBlockRegister = 0x0C;
constexpr std::uint64_t kPageRegister = 0x10;
constexpr std::uint64_t kLocalAddressRegister = 0x14;
// What the chip is, for the firmware to read.
constexpr std::uint64_t kPageSizeRegister = 0x20;
constexpr std::uint64_t kPagesPerBlockRegister = 0x24;
constexpr std::uint64_t kBlocksRegister = 0x28;

// What the command register can be told.
constexpr std::uint32_t kReadPage = 1;
constexpr std::uint32_t kProgramPage = 2;
constexpr std::uint32_t kEraseBlock = 3;
constexpr std::uint32_t kIdentify = 4;

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;
constexpr std::uint32_t kError = 1U << 1;
constexpr std::uint32_t kBusy = 1U << 2;

}  // namespace

FlashControllerLogic::FlashControllerLogic(NandPort& nand,
                                           MemoryPort& local_memory)
    : nand_(nand), local_memory_(local_memory) {}

bool FlashControllerLogic::ReadRegister(std::uint64_t offset,
                                        std::span<std::uint8_t> out) const {
  if (out.size() != kRegisterBytes) return false;
  const NandGeometry geometry = geometry_.value_or(NandGeometry{});
  switch (offset) {
    case kCommandRegister:
      StoreLittleEndian(std::uint32_t{0}, out);
      break;
    case kStatusRegister:
      StoreLittleEndian(status_, out);
      break;
    case kInterruptEnableRegister:
      StoreLittleEndian(interrupt_enable_, out);
      break;
    case kBlockRegister:
      StoreLittleEndian(block_, out);
      break;
    case kPageRegister:
      StoreLittleEndian(page_, out);
      break;
    case kLocalAddressRegister:
      StoreLittleEndian(local_address_, out);
      break;
    case kPageSizeRegister:
      StoreLittleEndian(geometry.page_size, out);
      break;
    case kPagesPerBlockRegister:
      StoreLittleEndian(geometry.pages_per_block, out);
      break;
    case kBlocksRegister:
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
    case kCommandRegister:
      if (job_ || value < kReadPage || value > kIdentify) return false;
      job_ = Job{.command = value,
                 .block = block_,
                 .page = page_,
                 .local_address = local_address_};
      status_ = kBusy;
      break;
    case kStatusRegister:
      status_ &= ~(value & (kDone | kError));
      break;
    case kInterruptEnableRegister:
      interrupt_enable_ = value & (kDone | kError);
      break;
    case kBlockRegister:
      block_ = value;
      break;
    case kPageRegister:
      page_ = value;
      break;
    case kLocalAddressRegister:
      local_address_ = value;
      break;
    default:
      return false;
  }
  return true;
}

bool FlashControllerLogic::CarryOut() {
  if (!job_) return false;
  status_ = Do(*job_) ? kDone : kError;
  job_.reset();
  return true;
}

bool FlashControllerLogic::Do(const Job& job) {
  switch (job.command) {
    case kReadPage: {
      if (!geometry_) return false;
      std::vector<std::uint8_t> page(geometry_->page_size);
      return nand_.ReadPage(job.block, job.page, page) &&
             local_memory_.Write(job.local_address, page);
    }
    case kProgramPage: {
      if (!geometry_) return false;
      std::vector<std::uint8_t> page(geometry_->page_size);
      return local_memory_.Read(job.local_address, page) &&
             nand_.ProgramPage(job.block, job.page, page);
    }
    case kEraseBlock:
      return nand_.EraseBlock(job.block);
    case kIdentify:
      geometry_ = nand_.Geometry();
      return geometry_.has_value();
    default:
      return false;
  }
}

}  // namespace socpuppet
