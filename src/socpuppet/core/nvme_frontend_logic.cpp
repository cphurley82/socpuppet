#include "socpuppet/core/nvme_frontend_logic.h"

#include <algorithm>
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
// Which submission queue the command that is waiting came from.
constexpr std::uint64_t kCommandQueueRegister = 0x10;
// The command that is waiting, 64 bytes of it.
constexpr std::uint64_t kCommandRegister = 0x40;

// The bits of the status register that say what the host has done. Each
// stays set until the CPU writes a one to it.
constexpr std::uint32_t kEnabled = 1U << 0;
constexpr std::uint32_t kDisabled = 1U << 1;
// And the bit that is set for as long as a command is waiting for the CPU.
constexpr std::uint32_t kCommandWaiting = 1U << 2;

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
  if (NvmeHostRegisters::IsInTheDoorbells(offset)) {
    const std::optional<NvmeHostRegisters::Doorbell> doorbell =
        NvmeHostRegisters::DoorbellWrite(offset, in);
    return doorbell && queues_.RingDoorbell(doorbell->number, doorbell->value);
  }
  const std::optional<NvmeHostRegisters::Enable> enable =
      host_registers_.Write(offset, in);
  if (!enable) return false;
  if (*enable == NvmeHostRegisters::Enable::kSet) {
    // The admin queues are the hardware's to set up: the host has said
    // where they are, in registers, before any command could say.
    host_registers_.CreateAdminQueues(queues_);
    events_ |= kEnabled;
  }
  if (*enable == NvmeHostRegisters::Enable::kCleared) events_ |= kDisabled;
  return true;
}

bool NvmeFrontendLogic::ReadCpuRegister(std::uint64_t offset,
                                        std::span<std::uint8_t> out) const {
  switch (offset) {
    case kStatusRegister:
      StoreLittleEndian(
          events_ | (command_ ? kCommandWaiting : std::uint32_t{0}), out);
      break;
    case kCommandQueueRegister:
      StoreLittleEndian(
          std::uint32_t{command_ ? command_->queue_id : std::uint16_t{0}}, out);
      break;
    case kCommandRegister:
      if (command_) {
        std::ranges::copy(command_->bytes, out.begin());
      } else {
        std::ranges::fill(out, std::uint8_t{0});
      }
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

bool NvmeFrontendLogic::Step() {
  if (command_) return false;
  command_ = queues_.Fetch();
  return command_.has_value();
}

}  // namespace socpuppet
