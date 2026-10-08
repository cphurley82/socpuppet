#include "socpuppet/core/nvme_controller.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "socpuppet/core/prp.h"
#include "spdk/nvme_spec.h"

namespace socpuppet {

namespace {

// There is one namespace, and namespaces are numbered from 1.
constexpr std::uint32_t kTheNamespace = 1;

// A block is 512 bytes, the size a disk has had since the floppy.
constexpr std::uint32_t kBlockSizeShift = 9;

// The controller registers end where the doorbells begin.
constexpr std::size_t kControllerRegistersSize =
    offsetof(spdk_nvme_registers, doorbell);

// The bytes of one of SPDK's structures, which are laid out exactly as the
// specification says they are in a register block or in the host's memory.
// (That takes a little-endian machine to build on, as SPDK's structures do.)
template <typename Structure>
std::span<std::uint8_t> BytesOf(Structure& structure) {
  return {reinterpret_cast<std::uint8_t*>(&structure), sizeof structure};
}

// The slot after `pointer` in a queue whose last slot is `last`.
std::uint16_t After(std::uint16_t pointer, std::uint16_t last) {
  return pointer == last ? std::uint16_t{0}
                         : static_cast<std::uint16_t>(pointer + 1);
}

// Whether an I/O queue may have this size, which the host gives counted
// from zero. A queue always keeps one slot empty, so that full and empty
// do not look alike, and a queue of one entry could hold nothing. There
// is no upper limit to check: the field's largest value is the largest
// size the controller says it takes (CAP.MQES).
bool IsAQueueSize(std::uint32_t size_from_zero) { return size_from_zero != 0; }

bool Fits(std::uint64_t offset, std::size_t length) {
  return offset <= kControllerRegistersSize &&
         length <= kControllerRegistersSize - offset;
}

// Where in the host's memory `length` bytes of a command's data are.
std::vector<HostExtent> Extents(NvmeController::HostMemory& host_memory,
                                const spdk_nvme_cmd& command,
                                std::size_t length) {
  return PrpExtents(command.dptr.prp.prp1, command.dptr.prp.prp2, length,
                    [&host_memory](std::uint64_t address) {
                      std::uint64_t entry = 0;
                      host_memory.Read(address, BytesOf(entry));
                      return entry;
                    });
}

}  // namespace

NvmeController::NvmeController(HostMemory& host_memory, std::uint64_t blocks,
                               std::size_t vectors)
    : host_memory_(host_memory),
      blocks_(blocks),
      vectors_(vectors),
      drive_(blocks << kBlockSizeShift) {}

bool NvmeController::ReadRegister(std::uint64_t offset,
                                  std::span<std::uint8_t> out) const {
  if (!Fits(offset, out.size())) return false;
  spdk_nvme_registers registers = Registers();
  std::ranges::copy(BytesOf(registers).subspan(offset, out.size()),
                    out.begin());
  return true;
}

bool NvmeController::WriteRegister(std::uint64_t offset,
                                   std::span<const std::uint8_t> in) {
  if (offset >= kControllerRegistersSize) return RingDoorbell(offset, in);
  if (!Fits(offset, in.size())) return false;
  // Lay the write over the registers as they are, and keep what the host
  // is allowed to change. A write to a read-only register changes nothing.
  spdk_nvme_registers registers = Registers();
  const bool was_enabled = registers.cc.bits.en;
  std::ranges::copy(in, BytesOf(registers).subspan(offset).begin());
  configuration_ = registers.cc.raw;
  admin_queue_sizes_ = registers.aqa.raw;
  admin_submission_queue_ = registers.asq;
  admin_completion_queue_ = registers.acq;
  if (!was_enabled && registers.cc.bits.en) Enable();
  if (was_enabled && !registers.cc.bits.en) Reset();
  return true;
}

// Setting CC.EN: the controller takes the admin queues from where the
// registers say they are, and is ready for admin commands.
void NvmeController::Enable() {
  spdk_nvme_aqa_register sizes{};
  sizes.raw = admin_queue_sizes_;
  submissions_[0] = {.exists = true,
                     .base = admin_submission_queue_,
                     .last = static_cast<std::uint16_t>(sizes.bits.asqs)};
  completions_[0] = {.exists = true,
                     .base = admin_completion_queue_,
                     .last = static_cast<std::uint16_t>(sizes.bits.acqs)};
}

// Clearing CC.EN is a controller reset: it does away with every queue. The
// registers keep what the host told them, and everything on the drive
// stays.
void NvmeController::Reset() {
  submissions_ = {};
  completions_ = {};
}

bool NvmeController::CarryOutOne() {
  // The lowest-numbered queue with a command that can be carried out, so
  // an admin command goes before any I/O command that is waiting. A
  // command whose completion queue is full has to wait: its completion
  // would land in the slot the host uses to tell full from empty, and the
  // one after it on a completion the host has not acknowledged.
  const auto has_work = [this](const SubmissionQueue& queue) {
    if (!queue.exists || queue.head == queue.tail) return false;
    const CompletionQueue& completions = completions_[queue.completion_queue];
    return After(completions.tail, completions.last) != completions.head;
  };
  std::uint16_t queue_id = 0;
  while (queue_id < kQueues && !has_work(submissions_[queue_id])) ++queue_id;
  if (queue_id == kQueues) return false;
  SubmissionQueue& submissions = submissions_[queue_id];
  CompletionQueue& completions = completions_[submissions.completion_queue];

  // Fetch the command.
  spdk_nvme_cmd command{};
  host_memory_.Read(submissions.base + (submissions.head * sizeof command),
                    BytesOf(command));
  submissions.head = After(submissions.head, submissions.last);

  // Do what it says.
  const Outcome outcome =
      queue_id == 0 ? CarryOutAdmin(command) : CarryOutIo(command);

  // Post its completion.
  spdk_nvme_cpl completion{};
  completion.cdw0 = outcome.result;
  completion.sqhd = submissions.head;
  completion.sqid = queue_id;
  completion.cid = command.cid;
  // The status code type is three bits wide. The mask is for GCC, which
  // cannot tell that an 8-bit value of 0 or 1 fits.
  completion.status.sct = outcome.status_type & 0x7;
  completion.status.sc = outcome.status;
  completion.status.p = completions.phase ? 1 : 0;
  host_memory_.Write(completions.base + (completions.tail * sizeof completion),
                     BytesOf(completion));
  completions.tail = After(completions.tail, completions.last);
  if (completions.tail == 0) completions.phase = !completions.phase;
  return true;
}

NvmeController::Outcome NvmeController::CommandSpecific(std::uint8_t status) {
  return {.status = status, .status_type = SPDK_NVME_SCT_COMMAND_SPECIFIC};
}

NvmeController::Outcome NvmeController::SendToHost(
    const spdk_nvme_cmd& command, std::span<const std::uint8_t> data) {
  std::size_t sent = 0;
  for (const HostExtent& extent : Extents(host_memory_, command, data.size())) {
    if (!host_memory_.Write(extent.address,
                            data.subspan(sent, extent.length))) {
      return {.status = SPDK_NVME_SC_DATA_TRANSFER_ERROR};
    }
    sent += extent.length;
  }
  return {};
}

NvmeController::Outcome NvmeController::FetchFromHost(
    const spdk_nvme_cmd& command, std::span<std::uint8_t> data) {
  std::size_t fetched = 0;
  for (const HostExtent& extent : Extents(host_memory_, command, data.size())) {
    if (!host_memory_.Read(extent.address,
                           data.subspan(fetched, extent.length))) {
      return {.status = SPDK_NVME_SC_DATA_TRANSFER_ERROR};
    }
    fetched += extent.length;
  }
  return {};
}

NvmeController::Outcome NvmeController::CarryOutAdmin(
    const spdk_nvme_cmd& command) {
  switch (command.opc) {
    case SPDK_NVME_OPC_CREATE_IO_CQ:
      return CreateIoCompletionQueue(command);
    case SPDK_NVME_OPC_CREATE_IO_SQ:
      return CreateIoSubmissionQueue(command);
    case SPDK_NVME_OPC_IDENTIFY:
      return Identify(command);
    case SPDK_NVME_OPC_SET_FEATURES:
      return SetFeatures(command);
    default:
      return {.status = SPDK_NVME_SC_INVALID_OPCODE};
  }
}

// Create I/O Completion Queue: the host has set a ring aside in its memory
// and says where it is, how long, and which interrupt vector goes with it.
NvmeController::Outcome NvmeController::CreateIoCompletionQueue(
    const spdk_nvme_cmd& command) {
  const std::size_t queue_id = command.cdw10_bits.create_io_q.qid;
  // Queue 0 is the admin queue, which the host does not create, and a
  // queue that exists is not created again: the host deletes it first.
  if (queue_id == 0 || queue_id >= kQueues || completions_[queue_id].exists) {
    return CommandSpecific(SPDK_NVME_SC_INVALID_QUEUE_IDENTIFIER);
  }
  if (!IsAQueueSize(command.cdw10_bits.create_io_q.qsize)) {
    return CommandSpecific(SPDK_NVME_SC_INVALID_QUEUE_SIZE);
  }
  // The host is told about this queue's completions on the vector it
  // names, which has to be one the function has a line for.
  if (command.cdw11_bits.create_io_cq.iv >= vectors_) {
    return CommandSpecific(SPDK_NVME_SC_INVALID_INTERRUPT_VECTOR);
  }
  completions_[queue_id] = {
      .exists = true,
      .base = command.dptr.prp.prp1,
      .last = static_cast<std::uint16_t>(command.cdw10_bits.create_io_q.qsize),
      .vector = static_cast<std::uint16_t>(command.cdw11_bits.create_io_cq.iv)};
  return {};
}

// Create I/O Submission Queue: the same for a ring of commands, and which
// completion queue their completions go to. That queue has to exist first,
// so a host creates the completion queue before the submission queue.
NvmeController::Outcome NvmeController::CreateIoSubmissionQueue(
    const spdk_nvme_cmd& command) {
  const std::size_t queue_id = command.cdw10_bits.create_io_q.qid;
  if (queue_id == 0 || queue_id >= kQueues || submissions_[queue_id].exists) {
    return CommandSpecific(SPDK_NVME_SC_INVALID_QUEUE_IDENTIFIER);
  }
  if (!IsAQueueSize(command.cdw10_bits.create_io_q.qsize)) {
    return CommandSpecific(SPDK_NVME_SC_INVALID_QUEUE_SIZE);
  }
  const std::size_t completion_queue = command.cdw11_bits.create_io_sq.cqid;
  if (completion_queue >= kQueues || !completions_[completion_queue].exists) {
    return CommandSpecific(SPDK_NVME_SC_COMPLETION_QUEUE_INVALID);
  }
  submissions_[queue_id] = {
      .exists = true,
      .base = command.dptr.prp.prp1,
      .last = static_cast<std::uint16_t>(command.cdw10_bits.create_io_q.qsize),
      .completion_queue = static_cast<std::uint16_t>(completion_queue)};
  return {};
}

// Identify: the host asks what the controller is and what it holds, and
// gets a 4 KiB page of description back.
NvmeController::Outcome NvmeController::Identify(const spdk_nvme_cmd& command) {
  switch (command.cdw10_bits.identify.cns) {
    case SPDK_NVME_IDENTIFY_CTRLR: {
      spdk_nvme_ctrlr_data controller{};
      controller.nn = 1;
      return SendToHost(command, BytesOf(controller));
    }
    case SPDK_NVME_IDENTIFY_NS: {
      if (command.nsid != kTheNamespace) {
        return {.status = SPDK_NVME_SC_INVALID_NAMESPACE_OR_FORMAT};
      }
      spdk_nvme_ns_data name_space{};
      name_space.nsze = blocks_;
      // One block format, which is therefore the one in use.
      name_space.lbaf[0].lbads = kBlockSizeShift;
      return SendToHost(command, BytesOf(name_space));
    }
    case SPDK_NVME_IDENTIFY_ACTIVE_NS_LIST: {
      // The namespaces in use, in rising order, with a zero after the last.
      spdk_nvme_ns_list list{};
      list.ns_list[0] = 1;
      return SendToHost(command, BytesOf(list));
    }
    default:
      return {.status = SPDK_NVME_SC_INVALID_FIELD};
  }
}

// Set Features: the host changes a setting. The one setting every driver
// changes is how many I/O queues it would like.
NvmeController::Outcome NvmeController::SetFeatures(
    const spdk_nvme_cmd& command) {
  switch (command.cdw10_bits.set_features.fid) {
    case SPDK_NVME_FEAT_NUMBER_OF_QUEUES: {
      // The answer is how many queues the controller has, whatever the
      // host asked for, and the host uses the smaller number. Both counts
      // are from zero: submission queues, then completion queues.
      spdk_nvme_feat_number_of_queues granted{};
      granted.bits.nsqr = kIoQueuePairs - 1U;
      granted.bits.ncqr = kIoQueuePairs - 1U;
      return {.result = granted.raw};
    }
    default:
      return {.status = SPDK_NVME_SC_INVALID_FIELD};
  }
}

NvmeController::Outcome NvmeController::CarryOutIo(
    const spdk_nvme_cmd& command) {
  switch (command.opc) {
    case SPDK_NVME_OPC_FLUSH:
      // Everything written is already as safe as it gets: it is in RAM,
      // and there is no cache in front of that.
      return {};
    case SPDK_NVME_OPC_READ:
      return Read(command);
    case SPDK_NVME_OPC_WRITE:
      return Write(command);
    default:
      return {.status = SPDK_NVME_SC_INVALID_OPCODE};
  }
}

// Read: the host asks for blocks, and the controller writes them into the
// host's memory.
NvmeController::Outcome NvmeController::Read(const spdk_nvme_cmd& command) {
  if (command.nsid != kTheNamespace) {
    return {.status = SPDK_NVME_SC_INVALID_NAMESPACE_OR_FORMAT};
  }
  const std::span<std::uint8_t> blocks = Blocks(command);
  if (blocks.empty()) return {.status = SPDK_NVME_SC_LBA_OUT_OF_RANGE};
  return SendToHost(command, blocks);
}

// Write: the other way. The controller reads the blocks out of the host's
// memory and keeps them.
NvmeController::Outcome NvmeController::Write(const spdk_nvme_cmd& command) {
  if (command.nsid != kTheNamespace) {
    return {.status = SPDK_NVME_SC_INVALID_NAMESPACE_OR_FORMAT};
  }
  const std::span<std::uint8_t> blocks = Blocks(command);
  if (blocks.empty()) return {.status = SPDK_NVME_SC_LBA_OUT_OF_RANGE};
  return FetchFromHost(command, blocks);
}

std::span<std::uint8_t> NvmeController::Blocks(const spdk_nvme_cmd& command) {
  // The starting block (the LBA, logical block address) is 64 bits in
  // dwords 10 and 11. The number of blocks is the low half of dword 12,
  // counted from zero.
  const std::uint64_t first =
      std::uint64_t{command.cdw11} << 32 | command.cdw10;
  const std::uint64_t count = (command.cdw12 & 0xFFFF) + std::uint64_t{1};
  // Checked in blocks, before anything is turned into bytes: a block
  // number can be large enough to wrap around as a byte offset.
  if (first > blocks_ || count > blocks_ - first) return {};
  return std::span{drive_}.subspan(first << kBlockSizeShift,
                                   count << kBlockSizeShift);
}

bool NvmeController::Interrupting(std::size_t vector) const {
  return std::ranges::any_of(
      completions_, [vector](const CompletionQueue& queue) {
        return queue.exists && queue.vector == vector && !queue.quieted &&
               queue.head != queue.tail;
      });
}

bool NvmeController::Quieted() const {
  return std::ranges::any_of(
      completions_, [](const CompletionQueue& queue) { return queue.quieted; });
}

void NvmeController::Rearm() {
  for (CompletionQueue& queue : completions_) queue.quieted = false;
}

spdk_nvme_registers NvmeController::Registers() const {
  spdk_nvme_registers registers{};
  // An I/O queue may have as many entries as the field can say: 65536.
  // The entries are in the host's memory, so they cost the controller
  // nothing.
  registers.cap.bits.mqes = 0xFFFF;
  registers.cc.raw = configuration_;
  // There is nothing to start up, so the controller is ready as soon as it
  // is enabled.
  registers.csts.bits.rdy = registers.cc.bits.en;
  registers.aqa.raw = admin_queue_sizes_;
  registers.asq = admin_submission_queue_;
  registers.acq = admin_completion_queue_;
  return registers;
}

bool NvmeController::RingDoorbell(std::uint64_t offset,
                                  std::span<const std::uint8_t> in) {
  // The doorbells are 32 bits each, in pairs, queue after queue: a
  // submission queue's tail, then the completion queue's head. The queue
  // pointer is the low half of what the host writes.
  std::uint32_t value = 0;
  const std::uint64_t from_first = offset - kControllerRegistersSize;
  if (in.size() != sizeof value || from_first % sizeof value != 0) return false;
  std::ranges::copy(in, BytesOf(value).begin());
  const std::uint64_t doorbell = from_first / sizeof value;
  const std::uint64_t queue_id = doorbell / 2;
  if (queue_id >= kQueues) return false;
  if (doorbell % 2 == 0) {
    SubmissionQueue& queue = submissions_[queue_id];
    // A tail that is not one of the queue's slots could never be reached,
    // and the controller would fetch commands for ever.
    if (!queue.exists || value > queue.last) return false;
    queue.tail = static_cast<std::uint16_t>(value);
  } else {
    CompletionQueue& queue = completions_[queue_id];
    if (!queue.exists || value > queue.last) return false;
    queue.head = static_cast<std::uint16_t>(value);
    queue.quieted = true;
  }
  return true;
}

}  // namespace socpuppet
