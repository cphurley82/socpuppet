#include "socpuppet/core/nvme_frontend_logic.h"

#include <algorithm>
#include <cstddef>
#include <optional>
#include <span>

#include "socpuppet/core/little_endian.h"

namespace socpuppet {

namespace {

// How long the host is told to wait for the controller to become ready, in
// units of 500 ms: a second, which is long enough for firmware to start.
constexpr std::uint8_t kReadyTimeout = 2;

// Where the CPU's registers are. Each is 32 bits wide.
constexpr std::uint64_t kStatusRegister = 0x00;
constexpr std::uint64_t kControlRegister = 0x08;
// What the frontend has: how many I/O queue pairs in the low half, and how
// many interrupt vectors in the high half.
constexpr std::uint64_t kLimitsRegister = 0x0C;
constexpr unsigned kVectorsShift = 16;
// Which submission queue the command that is waiting came from.
constexpr std::uint64_t kCommandQueueRegister = 0x10;
// What the completion of the waiting command is to say, and the register
// that has it posted.
constexpr std::uint64_t kCompletionResultRegister = 0x14;
constexpr std::uint64_t kCompletionStatusRegister = 0x18;
constexpr std::uint64_t kCompletionPostRegister = 0x1C;
// A queue the firmware has agreed to create: which, where it is in the
// host's memory, its last slot, and what goes with it, which is a
// completion queue's interrupt vector or a submission queue's completion
// queue. A write to the last register creates it.
constexpr std::uint64_t kQueueIdRegister = 0x20;
constexpr std::uint64_t kQueueBaseLowRegister = 0x24;
constexpr std::uint64_t kQueueBaseHighRegister = 0x28;
constexpr std::uint64_t kQueueLastRegister = 0x2C;
constexpr std::uint64_t kQueueLinkRegister = 0x30;
constexpr std::uint64_t kQueueCreateRegister = 0x34;
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

// What the queue-create register is told.
constexpr std::uint32_t kCompletionQueue = 1;
constexpr std::uint32_t kSubmissionQueue = 2;

// The last slot of the longest queue there can be: 65536 entries.
constexpr std::uint32_t kLongestQueuesLastSlot = 0xFFFF;

// Where in a command the host puts the identifier it gives it.
constexpr std::size_t kCommandIdOffset = 2;

// The completion status register has the status code in its low byte, and
// above it which list of codes that is from.
constexpr unsigned kStatusTypeShift = 8;

}  // namespace

NvmeFrontendLogic::NvmeFrontendLogic(MemoryPort& host_memory,
                                     std::size_t vectors)
    : queues_(host_memory), vectors_(vectors) {}

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
  if (*enable == NvmeHostRegisters::Enable::kCleared) {
    // A controller reset. The hardware's part of it is immediate.
    command_.reset();
    events_ |= kDisabled;
  }
  return true;
}

bool NvmeFrontendLogic::ReadCpuRegister(std::uint64_t offset,
                                        std::span<std::uint8_t> out) const {
  switch (offset) {
    case kStatusRegister:
      StoreLittleEndian(
          events_ | (CommandWaiting() ? kCommandWaiting : std::uint32_t{0}),
          out);
      break;
    case kLimitsRegister:
      StoreLittleEndian(static_cast<std::uint32_t>(vectors_ << kVectorsShift) |
                            NvmeQueues::kIoQueuePairs,
                        out);
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
    case kCompletionResultRegister:
      completion_result_ = value;
      break;
    case kCompletionStatusRegister:
      completion_status_ = value;
      break;
    case kCompletionPostRegister:
      if (!CommandWaiting()) return false;
      posting_ = true;
      break;
    case kQueueIdRegister:
      queue_.id = value;
      break;
    case kQueueBaseLowRegister:
      queue_.base = (queue_.base & ~std::uint64_t{0xFFFF'FFFF}) | value;
      break;
    case kQueueBaseHighRegister:
      queue_.base = (queue_.base & 0xFFFF'FFFF) | (std::uint64_t{value} << 32);
      break;
    case kQueueLastRegister:
      queue_.last = value;
      break;
    case kQueueLinkRegister:
      queue_.link = value;
      break;
    case kQueueCreateRegister:
      return CreateQueue(value);
    default:
      break;
  }
  return true;
}

bool NvmeFrontendLogic::CreateQueue(std::uint32_t kind) {
  // Queue 0 of each kind is the admin queue, which the frontend sets up
  // for itself when the host enables the controller.
  if (queue_.id == 0 || queue_.id >= NvmeQueues::kQueues ||
      queue_.last > kLongestQueuesLastSlot) {
    return false;
  }
  const NvmeQueues::Ring ring{.base = queue_.base,
                              .last = static_cast<std::uint16_t>(queue_.last)};
  switch (kind) {
    case kCompletionQueue:
      // Its completions are announced on an interrupt vector, which has to
      // be one the frontend has a line for.
      if (queues_.HasCompletionQueue(queue_.id) || queue_.link >= vectors_) {
        return false;
      }
      queues_.CreateCompletionQueue(queue_.id, ring,
                                    static_cast<std::uint16_t>(queue_.link));
      return true;
    case kSubmissionQueue:
      // Its commands' completions go to a completion queue, which has to
      // be there first.
      if (queues_.HasSubmissionQueue(queue_.id) ||
          !queues_.HasCompletionQueue(queue_.link)) {
        return false;
      }
      queues_.CreateSubmissionQueue(queue_.id, ring,
                                    static_cast<std::uint16_t>(queue_.link));
      return true;
    default:
      return false;
  }
}

bool NvmeFrontendLogic::Step() {
  bool did_something = false;
  if (posting_) {
    queues_.Post({.queue_id = command_->queue_id,
                  .command_id = LoadLittleEndian<std::uint16_t>(
                      std::span{command_->bytes}.subspan(kCommandIdOffset)),
                  .status = static_cast<std::uint8_t>(completion_status_),
                  .status_type = static_cast<std::uint8_t>(
                      (completion_status_ >> kStatusTypeShift) & 0x7),
                  .result = completion_result_});
    command_.reset();
    posting_ = false;
    did_something = true;
  }
  if (!command_) {
    command_ = queues_.Fetch();
    did_something = did_something || command_.has_value();
  }
  return did_something;
}

}  // namespace socpuppet
