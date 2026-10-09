#include "socpuppet/core/nvme_queues.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>

#include "spdk/nvme_spec.h"

namespace socpuppet {

namespace {

static_assert(sizeof(spdk_nvme_cmd) == NvmeQueues::kCommandBytes);

// The slot after `pointer` in a queue whose last slot is `last`.
std::uint16_t After(std::uint16_t pointer, std::uint16_t last) {
  return pointer == last ? std::uint16_t{0}
                         : static_cast<std::uint16_t>(pointer + 1);
}

}  // namespace

bool NvmeQueues::HasCompletionQueue(std::size_t queue_id) const {
  return queue_id < kQueues && completions_[queue_id].exists;
}

bool NvmeQueues::HasSubmissionQueue(std::size_t queue_id) const {
  return queue_id < kQueues && submissions_[queue_id].exists;
}

void NvmeQueues::CreateCompletionQueue(std::size_t queue_id, const Ring& ring,
                                       std::uint16_t vector) {
  completions_[queue_id] = {.exists = true, .ring = ring, .vector = vector};
}

void NvmeQueues::CreateSubmissionQueue(std::size_t queue_id, const Ring& ring,
                                       std::uint16_t completion_queue) {
  submissions_[queue_id] = {
      .exists = true, .ring = ring, .completion_queue = completion_queue};
}

void NvmeQueues::RemoveAll() {
  submissions_ = {};
  completions_ = {};
}

bool NvmeQueues::RingDoorbell(std::uint64_t doorbell, std::uint32_t value) {
  const std::uint64_t queue_id = doorbell / 2;
  if (queue_id >= kQueues) return false;
  if (doorbell % 2 == 0) {
    SubmissionQueue& queue = submissions_[queue_id];
    // A tail that is not one of the queue's slots could never be reached,
    // and the controller would fetch commands for ever.
    if (!queue.exists || value > queue.ring.last) return false;
    queue.tail = static_cast<std::uint16_t>(value);
  } else {
    CompletionQueue& queue = completions_[queue_id];
    if (!queue.exists || value > queue.ring.last) return false;
    queue.head = static_cast<std::uint16_t>(value);
    queue.quieted = true;
  }
  return true;
}

std::optional<NvmeQueues::Command> NvmeQueues::Fetch() {
  const auto has_work = [this](const SubmissionQueue& queue) {
    if (!queue.exists || queue.head == queue.tail) return false;
    const CompletionQueue& completions = completions_[queue.completion_queue];
    return After(completions.tail, completions.ring.last) != completions.head;
  };
  std::uint16_t queue_id = 0;
  while (queue_id < kQueues && !has_work(submissions_[queue_id])) ++queue_id;
  if (queue_id == kQueues) return std::nullopt;
  SubmissionQueue& queue = submissions_[queue_id];

  Command command{.queue_id = queue_id};
  host_memory_.Read(queue.ring.base + (queue.head * kCommandBytes),
                    command.bytes);
  queue.head = After(queue.head, queue.ring.last);
  return command;
}

void NvmeQueues::Post(const Completion& completion) {
  const SubmissionQueue& submissions = submissions_[completion.queue_id];
  CompletionQueue& completions = completions_[submissions.completion_queue];

  spdk_nvme_cpl entry{};
  entry.cdw0 = completion.result;
  entry.sqhd = submissions.head;
  entry.sqid = completion.queue_id;
  entry.cid = completion.command_id;
  // The status code type is three bits wide. The mask is for GCC, which
  // cannot tell that an 8-bit value of 0 or 1 fits.
  entry.status.sct = completion.status_type & 0x7;
  entry.status.sc = completion.status;
  entry.status.p = completions.phase ? 1 : 0;
  // The bytes of SPDK's structure are laid out exactly as the
  // specification says they are in the host's memory. (That takes a
  // little-endian machine to build on, as SPDK's structures do.)
  host_memory_.Write(
      completions.ring.base + (completions.tail * sizeof entry),
      std::span{reinterpret_cast<const std::uint8_t*>(&entry), sizeof entry});
  completions.tail = After(completions.tail, completions.ring.last);
  if (completions.tail == 0) completions.phase = !completions.phase;
}

bool NvmeQueues::Interrupting(std::size_t vector) const {
  return std::ranges::any_of(
      completions_, [vector](const CompletionQueue& queue) {
        return queue.exists && queue.vector == vector && !queue.quieted &&
               queue.head != queue.tail;
      });
}

bool NvmeQueues::Quieted() const {
  return std::ranges::any_of(
      completions_, [](const CompletionQueue& queue) { return queue.quieted; });
}

void NvmeQueues::Rearm() {
  for (CompletionQueue& queue : completions_) queue.quieted = false;
}

}  // namespace socpuppet
