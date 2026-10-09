#include "socpuppet/core/dma_engine_logic.h"

#include <algorithm>
#include <array>
#include <cstddef>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

namespace {

// Where the registers are. Each is 32 bits wide.
constexpr std::size_t kRegisterBytes = 4;
constexpr std::uint64_t kCommandRegister = 0x00;
constexpr std::uint64_t kStatusRegister = 0x04;
constexpr std::uint64_t kInterruptEnableRegister = 0x08;
constexpr std::uint64_t kHostAddressLowRegister = 0x0C;
constexpr std::uint64_t kHostAddressHighRegister = 0x10;
constexpr std::uint64_t kLocalAddressRegister = 0x14;
constexpr std::uint64_t kLengthRegister = 0x18;

// How many bytes the engine copies at a time.
constexpr std::size_t kPieceBytes = 4096;

// What the command register can be told.
constexpr std::uint32_t kFromHost = 1;
constexpr std::uint32_t kToHost = 2;

// Copies `length` bytes from one memory to another, a piece at a time, so
// that a long copy does not take as much of the simulator's memory as it
// moves. Returns false at the first piece either memory does not take, with
// the pieces before it already copied.
bool Copy(MemoryPort& source, std::uint64_t from, MemoryPort& destination,
          std::uint64_t to, std::uint64_t length) {
  std::array<std::uint8_t, kPieceBytes> buffer{};
  for (std::uint64_t left = length; left != 0;) {
    const std::span piece =
        std::span{buffer}.first(std::min<std::uint64_t>(left, kPieceBytes));
    if (!source.Read(from, piece) || !destination.Write(to, piece)) {
      return false;
    }
    from += piece.size();
    to += piece.size();
    left -= piece.size();
  }
  return true;
}

}  // namespace

DmaEngineLogic::DmaEngineLogic(MemoryPort& host_memory,
                               MemoryPort& local_memory)
    : host_memory_(host_memory), local_memory_(local_memory) {}

bool DmaEngineLogic::ReadRegister(std::uint64_t offset,
                                  std::span<std::uint8_t> out) const {
  if (out.size() != kRegisterBytes) return false;
  switch (offset) {
    case kCommandRegister:
      StoreLittleEndian(std::uint32_t{0}, out);
      break;
    case kStatusRegister:
      StoreLittleEndian(status_.Status(), out);
      break;
    case kInterruptEnableRegister:
      StoreLittleEndian(status_.InterruptEnable(), out);
      break;
    case kHostAddressLowRegister:
      StoreLittleEndian(static_cast<std::uint32_t>(host_address_), out);
      break;
    case kHostAddressHighRegister:
      StoreLittleEndian(static_cast<std::uint32_t>(host_address_ >> 32), out);
      break;
    case kLocalAddressRegister:
      StoreLittleEndian(local_address_, out);
      break;
    case kLengthRegister:
      StoreLittleEndian(length_, out);
      break;
    default:
      return false;
  }
  return true;
}

bool DmaEngineLogic::WriteRegister(std::uint64_t offset,
                                   std::span<const std::uint8_t> in) {
  if (in.size() != kRegisterBytes) return false;
  const auto value = LoadLittleEndian<std::uint32_t>(in);
  switch (offset) {
    case kCommandRegister:
      if (status_.Busy() || (value != kFromHost && value != kToHost)) {
        return false;
      }
      job_ = Job{.command = value,
                 .host_address = host_address_,
                 .local_address = local_address_,
                 .length = length_};
      status_.Start();
      break;
    case kStatusRegister:
      status_.WriteStatus(value);
      break;
    case kInterruptEnableRegister:
      status_.WriteInterruptEnable(value);
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
      return false;
  }
  return true;
}

bool DmaEngineLogic::CarryOut() {
  if (!status_.Busy()) return false;
  status_.Finish(Do(job_));
  return true;
}

bool DmaEngineLogic::Do(const Job& job) {
  if (job.length == 0) return false;
  return job.command == kFromHost
             ? Copy(host_memory_, job.host_address, local_memory_,
                    job.local_address, job.length)
             : Copy(local_memory_, job.local_address, host_memory_,
                    job.host_address, job.length);
}

}  // namespace socpuppet
