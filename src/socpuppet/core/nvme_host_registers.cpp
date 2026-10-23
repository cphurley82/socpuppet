#include "socpuppet/core/nvme_host_registers.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>

#include "spdk/nvme_spec.h"

namespace socpuppet {

namespace {

// The controller registers end where the doorbells begin.
constexpr std::size_t kControllerRegistersSize =
    offsetof(spdk_nvme_registers, doorbell);

// The bytes of one of SPDK's structures, which are laid out exactly as the
// specification says they are in a register block. (That takes a
// little-endian machine to build on, as SPDK's structures do.)
template <typename Structure>
std::span<std::uint8_t> BytesOf(Structure& structure) {
  return {reinterpret_cast<std::uint8_t*>(&structure), sizeof structure};
}

// A shutdown's status is the number the specification gives it.
static_assert(static_cast<int>(NvmeHostRegisters::Shutdown::kNone) ==
              SPDK_NVME_SHST_NORMAL);
static_assert(static_cast<int>(NvmeHostRegisters::Shutdown::kUnderWay) ==
              SPDK_NVME_SHST_OCCURRING);
static_assert(static_cast<int>(NvmeHostRegisters::Shutdown::kComplete) ==
              SPDK_NVME_SHST_COMPLETE);

// CAP, VS and CSTS, where SPDK's layout has them.
constexpr std::array<NvmeHostRegisters::Register, 3>
    kRegistersTheControllerSays{{{.offset = offsetof(spdk_nvme_registers, cap),
                                  .size = sizeof(spdk_nvme_registers::cap)},
                                 {.offset = offsetof(spdk_nvme_registers, vs),
                                  .size = sizeof(spdk_nvme_registers::vs)},
                                 {.offset = offsetof(spdk_nvme_registers, csts),
                                  .size = sizeof(spdk_nvme_registers::csts)}}};

bool Fits(std::uint64_t offset, std::size_t length) {
  return offset <= kControllerRegistersSize &&
         length <= kControllerRegistersSize - offset;
}

}  // namespace

bool NvmeHostRegisters::Read(std::uint64_t offset, std::span<std::uint8_t> out,
                             const Says& says) const {
  if (!Fits(offset, out.size())) return false;
  spdk_nvme_registers registers{};
  // An I/O queue may have as many entries as the field can say: 65536.
  // The entries are in the host's memory, so they cost the controller
  // nothing.
  registers.cap.bits.mqes = 0xFFFF;
  registers.cap.bits.to = says.ready_timeout;
  // The one command set it takes is NVM's, which is the drive's reads and
  // writes. UEFI's driver asks; Linux takes it for granted.
  registers.cap.bits.css = SPDK_NVME_CAP_CSS_NVM;
  registers.cc.raw = configuration_;
  registers.csts.bits.rdy = says.ready ? 1 : 0;
  // Two bits, which the mask says to the compiler: the numbers fit.
  registers.csts.bits.shst = static_cast<std::uint8_t>(says.shutdown) & 0x3U;
  registers.aqa.raw = admin_queue_sizes_;
  registers.asq = admin_submission_queue_;
  registers.acq = admin_completion_queue_;
  std::ranges::copy(BytesOf(registers).subspan(offset, out.size()),
                    out.begin());
  return true;
}

std::optional<NvmeHostRegisters::Enable> NvmeHostRegisters::Write(
    std::uint64_t offset, std::span<const std::uint8_t> in,
    NvmeQueues& queues) {
  if (offset >= kControllerRegistersSize) {
    // The doorbells are 32 bits each, in pairs, queue after queue. The
    // queue pointer is the low half of what the host writes.
    std::uint32_t value = 0;
    const std::uint64_t from_first = offset - kControllerRegistersSize;
    if (in.size() != sizeof value || from_first % sizeof value != 0) {
      return std::nullopt;
    }
    std::ranges::copy(in, BytesOf(value).begin());
    if (!queues.RingDoorbell(from_first / sizeof value, value)) {
      return std::nullopt;
    }
    return Enable::kUnchanged;
  }
  const std::optional<Enable> enable = WriteControllerRegister(offset, in);
  if (enable == Enable::kSet) CreateAdminQueues(queues);
  if (enable == Enable::kCleared) queues.RemoveAll();
  return enable;
}

std::span<const NvmeHostRegisters::Register>
NvmeHostRegisters::RegistersTheControllerSays() {
  return kRegistersTheControllerSays;
}

bool NvmeHostRegisters::IsCompletionHeadDoorbell(std::uint64_t offset) {
  // The doorbells are 32 bits each, in pairs: a submission queue's tail,
  // then its completion queue's head.
  return offset >= kControllerRegistersSize &&
         ((offset - kControllerRegistersSize) / sizeof(std::uint32_t)) % 2 == 1;
}

bool NvmeHostRegisters::Enabled() const {
  spdk_nvme_cc_register configuration{};
  configuration.raw = configuration_;
  return configuration.bits.en != 0;
}

bool NvmeHostRegisters::ShutdownAsked() const {
  spdk_nvme_cc_register configuration{};
  configuration.raw = configuration_;
  return configuration.bits.shn != 0;
}

std::optional<NvmeHostRegisters::Enable>
NvmeHostRegisters::WriteControllerRegister(std::uint64_t offset,
                                           std::span<const std::uint8_t> in) {
  if (!Fits(offset, in.size())) return std::nullopt;
  // Lay the write over the registers the host may change, as they are,
  // and keep those. What it laid over the others is dropped.
  spdk_nvme_registers registers{};
  registers.cc.raw = configuration_;
  registers.aqa.raw = admin_queue_sizes_;
  registers.asq = admin_submission_queue_;
  registers.acq = admin_completion_queue_;
  const bool was_enabled = registers.cc.bits.en;
  std::ranges::copy(in, BytesOf(registers).subspan(offset).begin());
  configuration_ = registers.cc.raw;
  admin_queue_sizes_ = registers.aqa.raw;
  admin_submission_queue_ = registers.asq;
  admin_completion_queue_ = registers.acq;
  if (!was_enabled && registers.cc.bits.en) return Enable::kSet;
  if (was_enabled && !registers.cc.bits.en) return Enable::kCleared;
  return Enable::kUnchanged;
}

void NvmeHostRegisters::CreateAdminQueues(NvmeQueues& queues) const {
  spdk_nvme_aqa_register sizes{};
  sizes.raw = admin_queue_sizes_;
  queues.CreateCompletionQueue(
      0,
      {.base = admin_completion_queue_,
       .last = static_cast<std::uint16_t>(sizes.bits.acqs)},
      /*vector=*/0);
  queues.CreateSubmissionQueue(
      0,
      {.base = admin_submission_queue_,
       .last = static_cast<std::uint16_t>(sizes.bits.asqs)},
      /*completion_queue=*/0);
}

}  // namespace socpuppet
