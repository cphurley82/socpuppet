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
constexpr std::size_t kRegisterBytes = 4;
constexpr std::uint64_t kControlRegister = 0x00;
constexpr std::uint64_t kStatusRegister = 0x04;
constexpr std::uint64_t kInterruptEnableRegister = 0x08;
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

// The completion status register is laid out as the status field of a
// completion is, less the phase bit: the status code in its low byte, and
// above it, in three bits, which list of codes that is from. The frontend
// passes those on and keeps nothing of the rest.
constexpr unsigned kStatusTypeShift = 8;
constexpr std::uint32_t kStatusCodeAndType = 0x7FF;

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
  const std::optional<NvmeHostRegisters::Enable> enable =
      host_registers_.Write(offset, in, queues_);
  if (!enable) return false;
  if (*enable == NvmeHostRegisters::Enable::kSet) events_ |= kEnabled;
  if (*enable == NvmeHostRegisters::Enable::kCleared) {
    // A controller reset. The hardware's part of it is immediate: the
    // queues are gone already, and so are the command that was waiting
    // and the firmware's word that it was ready. The rest is the
    // firmware's, and until it has acknowledged (see ResetIsPending) the
    // frontend keeps what it does about the old controller away from the
    // new one.
    command_.reset();
    posting_ = false;
    ready_ = false;
    events_ |= kDisabled;
  }
  return true;
}

bool NvmeFrontendLogic::ResetIsPending() const {
  return (events_ & kDisabled) != 0;
}

std::uint32_t NvmeFrontendLogic::Status() const {
  return events_ | (CommandWaiting() ? kCommandWaiting : std::uint32_t{0});
}

bool NvmeFrontendLogic::CpuInterrupting() const {
  return (Status() & interrupt_enable_) != 0;
}

bool NvmeFrontendLogic::ReadCpuRegister(std::uint64_t offset,
                                        std::span<std::uint8_t> out) const {
  if (offset >= kCommandRegister) {
    // The command, or any piece of it. With none waiting it is zeros.
    const std::uint64_t from = offset - kCommandRegister;
    if (from > NvmeQueues::kCommandBytes ||
        out.size() > NvmeQueues::kCommandBytes - from) {
      return false;
    }
    std::ranges::fill(out, std::uint8_t{0});
    if (command_) {
      std::ranges::copy(std::span{command_->bytes}.subspan(from, out.size()),
                        out.begin());
    }
    return true;
  }
  if (out.size() != kRegisterBytes) return false;
  switch (offset) {
    case kStatusRegister:
      StoreLittleEndian(Status(), out);
      break;
    case kInterruptEnableRegister:
      StoreLittleEndian(interrupt_enable_, out);
      break;
    case kControlRegister:
      StoreLittleEndian(ready_ ? kReady : std::uint32_t{0}, out);
      break;
    case kCompletionResultRegister:
      StoreLittleEndian(completion_result_, out);
      break;
    case kCompletionStatusRegister:
      StoreLittleEndian(completion_status_, out);
      break;
    case kCompletionPostRegister:
    case kQueueCreateRegister:
      StoreLittleEndian(std::uint32_t{0}, out);
      break;
    case kQueueIdRegister:
      StoreLittleEndian(queue_.id, out);
      break;
    case kQueueBaseLowRegister:
      StoreLittleEndian(static_cast<std::uint32_t>(queue_.base), out);
      break;
    case kQueueBaseHighRegister:
      StoreLittleEndian(static_cast<std::uint32_t>(queue_.base >> 32), out);
      break;
    case kQueueLastRegister:
      StoreLittleEndian(queue_.last, out);
      break;
    case kQueueLinkRegister:
      StoreLittleEndian(queue_.link, out);
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
    default:
      return false;
  }
  return true;
}

bool NvmeFrontendLogic::WriteCpuRegister(std::uint64_t offset,
                                         std::span<const std::uint8_t> in) {
  if (in.size() != kRegisterBytes) return false;
  const auto value = LoadLittleEndian<std::uint32_t>(in);
  switch (offset) {
    case kStatusRegister:
      events_ &= ~value;
      break;
    case kInterruptEnableRegister:
      interrupt_enable_ = value & (kEnabled | kDisabled | kCommandWaiting);
      break;
    case kControlRegister:
      // Ready is said of the controller the host has enabled now. Said to
      // no one, or of the controller as it was before a reset, it is not
      // heard.
      ready_ = (value & kReady) != 0 && host_registers_.Enabled() &&
               !ResetIsPending();
      break;
    case kCompletionResultRegister:
      completion_result_ = value;
      break;
    case kCompletionStatusRegister:
      completion_status_ = value & kStatusCodeAndType;
      break;
    case kCompletionPostRegister:
      if (value != 1) return false;
      // The command the firmware was dealing with went with the reset.
      // That is not the firmware's mistake, so the write is taken.
      if (ResetIsPending()) break;
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
      // A queue the firmware agreed to before a reset is not one of the
      // controller's after it.
      if (ResetIsPending()) break;
      return CreateQueue(value);
    default:
      return false;
  }
  return true;
}

bool NvmeFrontendLogic::CreateQueue(std::uint32_t kind) {
  // No command can have asked for a queue of a controller the host does
  // not have enabled. And queue 0 of each kind is the admin queue, which
  // the frontend sets up for itself when the host enables the controller.
  if (!host_registers_.Enabled() || queue_.id == 0 ||
      queue_.id >= NvmeQueues::kQueues ||
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
  // Nothing is fetched for firmware that has not yet let go of what it
  // had before the reset.
  if (ResetIsPending()) return false;
  bool did_something = false;
  if (posting_) {
    queues_.Post(*command_,
                 {.status = static_cast<std::uint8_t>(completion_status_),
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
