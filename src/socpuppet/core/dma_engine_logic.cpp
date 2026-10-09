#include "socpuppet/core/dma_engine_logic.h"

#include <vector>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

namespace {

// Where the registers are. Each is 32 bits wide.
constexpr std::uint64_t kCommandRegister = 0x00;
constexpr std::uint64_t kStatusRegister = 0x04;
constexpr std::uint64_t kHostAddressLowRegister = 0x0C;
constexpr std::uint64_t kHostAddressHighRegister = 0x10;
constexpr std::uint64_t kLocalAddressRegister = 0x14;
constexpr std::uint64_t kLengthRegister = 0x18;

}  // namespace

DmaEngineLogic::DmaEngineLogic(MemoryPort& host_memory,
                               MemoryPort& local_memory)
    : host_memory_(host_memory), local_memory_(local_memory) {}

bool DmaEngineLogic::ReadRegister(std::uint64_t offset,
                                  std::span<std::uint8_t> out) const {
  if (offset == kStatusRegister) StoreLittleEndian(status_.Status(), out);
  return true;
}

bool DmaEngineLogic::WriteRegister(std::uint64_t offset,
                                   std::span<const std::uint8_t> in) {
  const auto value = LoadLittleEndian<std::uint32_t>(in);
  switch (offset) {
    case kCommandRegister:
      job_ = Job{.command = value,
                 .host_address = host_address_,
                 .local_address = local_address_,
                 .length = length_};
      status_.Start();
      break;
    case kHostAddressLowRegister:
      host_address_ = (host_address_ & ~std::uint64_t{0xFFFF'FFFF}) | value;
      break;
    case kHostAddressHighRegister:
      host_address_ =
          (host_address_ & 0xFFFF'FFFF) | (std::uint64_t{value} << 32);
      break;
    case kLocalAddressRegister:
      local_address_ = value;
      break;
    case kLengthRegister:
      length_ = value;
      break;
    default:
      break;
  }
  return true;
}

bool DmaEngineLogic::CarryOut() {
  if (!job_) return false;
  status_.Finish(Do(*job_));
  job_.reset();
  return true;
}

bool DmaEngineLogic::Do(const Job& job) {
  std::vector<std::uint8_t> bytes(job.length);
  host_memory_.Read(job.host_address, bytes);
  local_memory_.Write(job.local_address, bytes);
  return true;
}

}  // namespace socpuppet
