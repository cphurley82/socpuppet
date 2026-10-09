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

// The bits of the status register.
constexpr std::uint32_t kDone = 1U << 0;
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
      command_ = value;
      status_ |= kBusy;
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
  command_ = 0;
  std::vector<std::uint8_t> page(nand_.Geometry()->page_size);
  nand_.ReadPage(block_, page_, page);
  local_memory_.Write(local_, page);
  status_ |= kDone;
  return true;
}

}  // namespace socpuppet
