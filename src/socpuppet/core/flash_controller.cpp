#include "socpuppet/core/flash_controller.h"

#include <vector>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

namespace {

// Where the registers are. Each is 32 bits wide.
constexpr std::uint64_t kCommandRegister = 0x00;
constexpr std::uint64_t kStatusRegister = 0x04;
constexpr std::uint64_t kBlockRegister = 0x0C;
constexpr std::uint64_t kPageRegister = 0x10;
constexpr std::uint64_t kLocalRegister = 0x14;

// What the command register can be told.
constexpr std::uint32_t kReadPage = 1;
constexpr std::uint32_t kProgramPage = 2;
constexpr std::uint32_t kEraseBlock = 3;

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;
constexpr std::uint32_t kError = 1U << 1;
constexpr std::uint32_t kBusy = 1U << 2;

}  // namespace

FlashController::FlashController(NandPort& nand, MemoryPort& local_memory)
    : nand_(nand), local_memory_(local_memory) {}

bool FlashController::ReadRegister(std::uint64_t offset,
                                   std::span<std::uint8_t> out) {
  if (offset == kStatusRegister) StoreLittleEndian(status_, out);
  return true;
}

bool FlashController::WriteRegister(std::uint64_t offset,
                                    std::span<const std::uint8_t> in) {
  const auto value = LoadLittleEndian<std::uint32_t>(in);
  switch (offset) {
    case kCommandRegister:
      if (command_ != 0 || value < kReadPage || value > kEraseBlock) {
        return false;
      }
      command_ = value;
      status_ |= kBusy;
      break;
    case kStatusRegister:
      status_ &= ~value;
      break;
    case kBlockRegister:
      block_ = value;
      break;
    case kPageRegister:
      page_ = value;
      break;
    case kLocalRegister:
      local_ = value;
      break;
    default:
      break;
  }
  return true;
}

bool FlashController::CarryOut() {
  if (command_ == 0) return false;
  status_ = Do(command_) ? kDone : kError;
  command_ = 0;
  return true;
}

bool FlashController::Do(std::uint32_t command) {
  std::vector<std::uint8_t> page(nand_.Geometry()->page_size);
  switch (command) {
    case kReadPage:
      return nand_.ReadPage(block_, page_, page) &&
             local_memory_.Write(local_, page);
    case kProgramPage:
      return local_memory_.Read(local_, page) &&
             nand_.ProgramPage(block_, page_, page);
    case kEraseBlock:
      return nand_.EraseBlock(block_);
    default:
      return false;
  }
}

}  // namespace socpuppet
