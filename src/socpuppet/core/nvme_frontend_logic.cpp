#include "socpuppet/core/nvme_frontend_logic.h"

#include <optional>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

namespace {

// How long the host is told to wait for the controller to become ready, in
// units of 500 ms: a second, which is long enough for firmware to start.
constexpr std::uint8_t kReadyTimeout = 2;

// Where the CPU's registers are. Each is 32 bits wide.
constexpr std::uint64_t kStatusRegister = 0x00;
constexpr std::uint64_t kControlRegister = 0x08;

// The bits of the status register that say what the host has done. Each
// stays set until the CPU writes a one to it.
constexpr std::uint32_t kEnabled = 1U << 0;
constexpr std::uint32_t kDisabled = 1U << 1;

// The bit of the control register by which firmware says it is ready for
// the host's commands. The host sees it as CSTS.RDY.
constexpr std::uint32_t kReady = 1U << 0;

}  // namespace

NvmeFrontendLogic::NvmeFrontendLogic(MemoryPort& host_memory,
                                     std::size_t /*vectors*/)
    : queues_(host_memory) {}

bool NvmeFrontendLogic::ReadHostRegister(std::uint64_t offset,
                                         std::span<std::uint8_t> out) const {
  return host_registers_.Read(
      offset, out, {.ready_timeout = kReadyTimeout, .ready = ready_});
}

bool NvmeFrontendLogic::WriteHostRegister(std::uint64_t offset,
                                          std::span<const std::uint8_t> in) {
  const std::optional<NvmeHostRegisters::Enable> enable =
      host_registers_.Write(offset, in);
  if (!enable) return false;
  if (*enable == NvmeHostRegisters::Enable::kSet) events_ |= kEnabled;
  if (*enable == NvmeHostRegisters::Enable::kCleared) events_ |= kDisabled;
  return true;
}

bool NvmeFrontendLogic::ReadCpuRegister(std::uint64_t offset,
                                        std::span<std::uint8_t> out) const {
  switch (offset) {
    case kStatusRegister:
      StoreLittleEndian(events_, out);
      break;
    default:
      break;
  }
  return true;
}

bool NvmeFrontendLogic::WriteCpuRegister(std::uint64_t offset,
                                         std::span<const std::uint8_t> in) {
  const auto value = LoadLittleEndian<std::uint32_t>(in);
  switch (offset) {
    case kStatusRegister:
      events_ &= ~value;
      break;
    case kControlRegister:
      ready_ = (value & kReady) != 0;
      break;
    default:
      break;
  }
  return true;
}

}  // namespace socpuppet
