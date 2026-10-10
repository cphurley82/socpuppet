#include "socpuppet/core/nvme_frontend_logic.h"

#include <algorithm>
#include <cstddef>
#include <optional>
#include <span>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/regs/nvme_frontend.h"

namespace socpuppet {

namespace {

// How long the host is told to wait for the controller to become ready, in
// units of 500 ms: a second, which is long enough for firmware to start.
constexpr std::uint8_t kReadyTimeout = 2;

// Each of the CPU's registers is 32 bits wide. Where each one is, what
// its bits are and what it can be told are the register map's names for
// them (regs/nvme_frontend.rdl), which the driver and the docs go by as
// well.
constexpr std::size_t kRegisterBytes = 4;

// The register map gives the waiting command as many bytes as NVMe says a
// command has.
static_assert(NVME_FRONTEND_COMMAND_SIZE == NvmeQueues::kCommandBytes);

// What of the status register can interrupt, which is all of it.
constexpr std::uint32_t kCanInterrupt =
    NVME_FRONTEND_INTERRUPT_ENABLE_ENABLED |
    NVME_FRONTEND_INTERRUPT_ENABLE_DISABLED |
    NVME_FRONTEND_INTERRUPT_ENABLE_COMMAND_WAITING;

// What of the completion status register is kept: the status code, and
// which list of codes it is from. The frontend passes those on and keeps
// nothing of the rest.
constexpr std::uint32_t kStatusCodeAndType =
    NVME_FRONTEND_COMPLETION_STATUS_CODE_MASK |
    NVME_FRONTEND_COMPLETION_STATUS_TYPE_MASK;

// The last slot of the longest queue there can be: 65536 entries.
constexpr std::uint32_t kLongestQueuesLastSlot = 0xFFFF;

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
  if (*enable == NvmeHostRegisters::Enable::kSet)
    events_ |= NVME_FRONTEND_STATUS_ENABLED;
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
    events_ |= NVME_FRONTEND_STATUS_DISABLED;
  }
  return true;
}

bool NvmeFrontendLogic::ResetIsPending() const {
  return (events_ & NVME_FRONTEND_STATUS_DISABLED) != 0;
}

std::uint32_t NvmeFrontendLogic::Status() const {
  return events_ | (CommandWaiting() ? NVME_FRONTEND_STATUS_COMMAND_WAITING
                                     : std::uint32_t{0});
}

bool NvmeFrontendLogic::CpuInterrupting() const {
  return (Status() & interrupt_enable_) != 0;
}

bool NvmeFrontendLogic::ReadCpuRegister(std::uint64_t offset,
                                        std::span<std::uint8_t> out) const {
  if (offset >= NVME_FRONTEND_COMMAND) {
    // The command, or any piece of it. With none waiting it is zeros.
    const std::uint64_t from = offset - NVME_FRONTEND_COMMAND;
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
    case NVME_FRONTEND_STATUS:
      StoreLittleEndian(Status(), out);
      break;
    case NVME_FRONTEND_INTERRUPT_ENABLE:
      StoreLittleEndian(interrupt_enable_, out);
      break;
    case NVME_FRONTEND_CONTROL:
      StoreLittleEndian(ready_ ? NVME_FRONTEND_CONTROL_READY : std::uint32_t{0},
                        out);
      break;
    case NVME_FRONTEND_COMPLETION_RESULT:
      StoreLittleEndian(completion_result_, out);
      break;
    case NVME_FRONTEND_COMPLETION_STATUS:
      StoreLittleEndian(completion_status_, out);
      break;
    case NVME_FRONTEND_COMPLETION_POST:
    case NVME_FRONTEND_QUEUE_CREATE:
      StoreLittleEndian(std::uint32_t{0}, out);
      break;
    case NVME_FRONTEND_QUEUE_ID:
      StoreLittleEndian(queue_.id, out);
      break;
    case NVME_FRONTEND_QUEUE_BASE_LOW:
      StoreLittleEndian(static_cast<std::uint32_t>(queue_.base), out);
      break;
    case NVME_FRONTEND_QUEUE_BASE_HIGH:
      StoreLittleEndian(static_cast<std::uint32_t>(queue_.base >> 32), out);
      break;
    case NVME_FRONTEND_QUEUE_LAST:
      StoreLittleEndian(queue_.last, out);
      break;
    case NVME_FRONTEND_QUEUE_LINK:
      StoreLittleEndian(queue_.link, out);
      break;
    case NVME_FRONTEND_LIMITS:
      StoreLittleEndian(static_cast<std::uint32_t>(
                            vectors_ << NVME_FRONTEND_LIMITS_VECTORS_SHIFT) |
                            (std::uint32_t{NvmeQueues::kIoQueuePairs}
                             << NVME_FRONTEND_LIMITS_IO_QUEUE_PAIRS_SHIFT),
                        out);
      break;
    case NVME_FRONTEND_COMMAND_QUEUE:
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
    case NVME_FRONTEND_STATUS:
      events_ &= ~value;
      break;
    case NVME_FRONTEND_INTERRUPT_ENABLE:
      interrupt_enable_ = value & kCanInterrupt;
      break;
    case NVME_FRONTEND_CONTROL:
      // Ready is said of the controller the host has enabled now. Said to
      // no one, or of the controller as it was before a reset, it is not
      // heard.
      ready_ = (value & NVME_FRONTEND_CONTROL_READY) != 0 &&
               host_registers_.Enabled() && !ResetIsPending();
      break;
    case NVME_FRONTEND_COMPLETION_RESULT:
      completion_result_ = value;
      break;
    case NVME_FRONTEND_COMPLETION_STATUS:
      completion_status_ = value & kStatusCodeAndType;
      break;
    case NVME_FRONTEND_COMPLETION_POST:
      if (value != NVME_FRONTEND_COMPLETION_POST_NOW) return false;
      // The command the firmware was dealing with went with the reset.
      // That is not the firmware's mistake, so the write is taken.
      if (ResetIsPending()) break;
      if (!CommandWaiting()) return false;
      posting_ = true;
      break;
    case NVME_FRONTEND_QUEUE_ID:
      queue_.id = value;
      break;
    case NVME_FRONTEND_QUEUE_BASE_LOW:
      queue_.base = (queue_.base & ~std::uint64_t{0xFFFF'FFFF}) | value;
      break;
    case NVME_FRONTEND_QUEUE_BASE_HIGH:
      queue_.base = (queue_.base & 0xFFFF'FFFF) | (std::uint64_t{value} << 32);
      break;
    case NVME_FRONTEND_QUEUE_LAST:
      queue_.last = value;
      break;
    case NVME_FRONTEND_QUEUE_LINK:
      queue_.link = value;
      break;
    case NVME_FRONTEND_QUEUE_CREATE:
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
    case NVME_FRONTEND_QUEUE_CREATE_COMPLETION_QUEUE:
      // Its completions are announced on an interrupt vector, which has to
      // be one the frontend has a line for.
      if (queues_.HasCompletionQueue(queue_.id) || queue_.link >= vectors_) {
        return false;
      }
      queues_.CreateCompletionQueue(queue_.id, ring,
                                    static_cast<std::uint16_t>(queue_.link));
      return true;
    case NVME_FRONTEND_QUEUE_CREATE_SUBMISSION_QUEUE:
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
  if (posting_ && command_) {
    queues_.Post(
        *command_,
        {.status = static_cast<std::uint8_t>(
             (completion_status_ & NVME_FRONTEND_COMPLETION_STATUS_CODE_MASK) >>
             NVME_FRONTEND_COMPLETION_STATUS_CODE_SHIFT),
         .status_type = static_cast<std::uint8_t>(
             (completion_status_ & NVME_FRONTEND_COMPLETION_STATUS_TYPE_MASK) >>
             NVME_FRONTEND_COMPLETION_STATUS_TYPE_SHIFT),
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
