#include "socpuppet/core/ucie_link_registers.h"

#include <cstdint>
#include <span>
#include <utility>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/ucie_link_state.h"
#include "socpuppet/regs/ucie_link.h"

namespace socpuppet {
namespace {

constexpr std::size_t kRegisterBytes = 4;

// The register map says two things twice, once as a number of its own and
// once in a register that firmware reads. They have to agree: how long the
// capability is, and where the block its locator points at starts.
static_assert((UCIE_LINK_DVSEC_HEADER_1_AT_RESET &
               UCIE_LINK_DVSEC_HEADER_1_LENGTH_MASK) >>
                  UCIE_LINK_DVSEC_HEADER_1_LENGTH_SHIFT ==
              UCIE_LINK_SIZE);
static_assert((UCIE_LINK_REGISTER_LOCATOR_AT_RESET &
               UCIE_LINK_REGISTER_LOCATOR_OFFSET_MASK) >>
                  UCIE_LINK_REGISTER_LOCATOR_OFFSET_SHIFT ==
              UCIE_LINK_TRAINING_STATE);

// What the mailbox's registers hold are UCIe's own numbers for a sideband
// packet's opcode and for how an access turned out, so the register map's
// names for them have to be those numbers.
static_assert(UCIE_LINK_MAILBOX_OPCODE_MEMORY_READ_32B ==
              static_cast<std::uint32_t>(SidebandOpcode::kMemoryRead32b));
static_assert(UCIE_LINK_MAILBOX_OPCODE_MEMORY_WRITE_32B ==
              static_cast<std::uint32_t>(SidebandOpcode::kMemoryWrite32b));
static_assert(UCIE_LINK_MAILBOX_STATUS_CODE_SUCCESS ==
              static_cast<std::uint32_t>(SidebandStatus::kSuccess));
static_assert(UCIE_LINK_MAILBOX_STATUS_CODE_UNSUPPORTED_REQUEST ==
              static_cast<std::uint32_t>(SidebandStatus::kUnsupportedRequest));

// The class starts with the die held in reset, as the register map has
// the reset register come out of reset.
static_assert((UCIE_LINK_DIE_RESET_AT_RESET & UCIE_LINK_DIE_RESET_ASSERTED) !=
              0);

// How wide UCIe's opcodes are: five bits of a sideband packet's header.
constexpr std::uint32_t kOpcodeBits = 0x1F;

// The register map's number for a state of link training.
std::uint32_t CodeOf(LinkTrainingState state) {
  switch (state) {
    case LinkTrainingState::kReset:
      return UCIE_LINK_TRAINING_STATE_RESET;
    case LinkTrainingState::kSbinit:
      return UCIE_LINK_TRAINING_STATE_SBINIT;
    case LinkTrainingState::kMbinit:
      return UCIE_LINK_TRAINING_STATE_MBINIT;
    case LinkTrainingState::kMbtrain:
      return UCIE_LINK_TRAINING_STATE_MBTRAIN;
    case LinkTrainingState::kLinkinit:
      return UCIE_LINK_TRAINING_STATE_LINKINIT;
    case LinkTrainingState::kActive:
      return UCIE_LINK_TRAINING_STATE_ACTIVE;
    case LinkTrainingState::kTrainError:
      return UCIE_LINK_TRAINING_STATE_TRAIN_ERROR;
  }
  return UCIE_LINK_TRAINING_STATE_TRAIN_ERROR;
}

bool IsUp(LinkTrainingState state) {
  return state == LinkTrainingState::kActive;
}

bool IsTraining(LinkTrainingState state) {
  switch (state) {
    case LinkTrainingState::kSbinit:
    case LinkTrainingState::kMbinit:
    case LinkTrainingState::kMbtrain:
    case LinkTrainingState::kLinkinit:
      return true;
    case LinkTrainingState::kReset:
    case LinkTrainingState::kActive:
    case LinkTrainingState::kTrainError:
      return false;
  }
  return false;
}

}  // namespace

bool UcieLinkRegisters::ReadRegister(std::uint64_t offset,
                                     std::span<std::uint8_t> out) const {
  if (out.size() != kRegisterBytes ||
      offset > UCIE_LINK_SIZE - kRegisterBytes) {
    return false;
  }
  StoreLittleEndian(RegisterAt(offset), out);
  return true;
}

bool UcieLinkRegisters::WriteRegister(std::uint64_t offset,
                                      std::span<const std::uint8_t> in) {
  if (in.size() != kRegisterBytes || offset > UCIE_LINK_SIZE - kRegisterBytes) {
    return false;
  }
  return Set(offset, LoadLittleEndian<std::uint32_t>(in));
}

std::uint32_t UcieLinkRegisters::RegisterAt(std::uint64_t offset) const {
  switch (offset) {
    // The three headers and the locator say what the capability is, and
    // never change: each holds what the register map has it hold at reset.
    case UCIE_LINK_EXTENDED_CAPABILITY_HEADER:
      return UCIE_LINK_EXTENDED_CAPABILITY_HEADER_AT_RESET;
    case UCIE_LINK_DVSEC_HEADER_1:
      return UCIE_LINK_DVSEC_HEADER_1_AT_RESET;
    case UCIE_LINK_DVSEC_HEADER_2:
      return UCIE_LINK_DVSEC_HEADER_2_AT_RESET;
    case UCIE_LINK_STATUS:
      return LinkStatus();
    case UCIE_LINK_EVENT_NOTIFICATION:
      return status_changed_interrupt_
                 ? UCIE_LINK_EVENT_NOTIFICATION_STATUS_CHANGED
                 : 0;
    case UCIE_LINK_REGISTER_LOCATOR:
      return UCIE_LINK_REGISTER_LOCATOR_AT_RESET;
    case UCIE_LINK_TRAINING_STATE:
      return CodeOf(state_);
    case UCIE_LINK_DIE_RESET:
      return reset_ ? UCIE_LINK_DIE_RESET_ASSERTED : 0U;
    case UCIE_LINK_MAILBOX_OPCODE:
      return static_cast<std::uint32_t>(mailbox_.opcode);
    case UCIE_LINK_MAILBOX_ADDRESS:
      return mailbox_.address;
    case UCIE_LINK_MAILBOX_DATA:
      return answer_;
    case UCIE_LINK_MAILBOX_STATUS:
      return (static_cast<std::uint32_t>(answer_status_)
              << UCIE_LINK_MAILBOX_STATUS_CODE_SHIFT) |
             (mailbox_busy_ ? UCIE_LINK_MAILBOX_STATUS_BUSY : 0);
    default:
      // Including link control, fault injection and the mailbox trigger,
      // which are actions and read back as nothing to do.
      return 0;
  }
}

bool UcieLinkRegisters::Set(std::uint64_t offset, std::uint32_t value) {
  switch (offset) {
    case UCIE_LINK_CONTROL:
      if ((value & UCIE_LINK_CONTROL_START_TRAINING) != 0)
        asked_.start_training = true;
      if ((value & UCIE_LINK_CONTROL_RETRAIN) != 0) asked_.retrain = true;
      return true;
    case UCIE_LINK_STATUS:
      // The bits that say something happened are cleared by writing a one
      // to them, so that firmware cannot lose one it has not seen.
      if ((value & UCIE_LINK_STATUS_CHANGED) != 0) status_changed_ = false;
      if ((value & UCIE_LINK_STATUS_UNCORRECTABLE_FATAL) != 0) fatal_ = false;
      return true;
    case UCIE_LINK_EVENT_NOTIFICATION:
      status_changed_interrupt_ =
          (value & UCIE_LINK_EVENT_NOTIFICATION_STATUS_CHANGED) != 0;
      return true;
    case UCIE_LINK_DIE_RESET:
      reset_ = (value & UCIE_LINK_DIE_RESET_ASSERTED) != 0;
      return true;
    case UCIE_LINK_FAULT_INJECTION:
      if ((value & UCIE_LINK_FAULT_INJECTION_BREAK) != 0) asked_.fault = true;
      return true;
    case UCIE_LINK_MAILBOX_OPCODE:
      mailbox_.opcode = static_cast<SidebandOpcode>(value & kOpcodeBits);
      return true;
    case UCIE_LINK_MAILBOX_ADDRESS:
      mailbox_.address = value;
      return true;
    case UCIE_LINK_MAILBOX_DATA:
      mailbox_.data = value;
      return true;
    case UCIE_LINK_MAILBOX_TRIGGER:
      if ((value & UCIE_LINK_MAILBOX_TRIGGER_GO) != 0) {
        asked_.mailbox = mailbox_;
        mailbox_busy_ = true;
      }
      return true;
    default:
      // A register that says something rather than being told something.
      return false;
  }
}

UcieLinkRegisters::Commands UcieLinkRegisters::TakeCommands() {
  return std::exchange(asked_, {});
}

void UcieLinkRegisters::LinkIs(LinkTrainingState state) {
  state_ = state;
  const bool up = IsUp(state);
  if (up != link_was_up_) status_changed_ = true;
  link_was_up_ = up;
}

void UcieLinkRegisters::FatalReported() { fatal_ = true; }

void UcieLinkRegisters::MailboxAnswered(SidebandStatus status,
                                        std::uint32_t data) {
  answer_status_ = status;
  answer_ = data;
  mailbox_busy_ = false;
}

std::uint32_t UcieLinkRegisters::LinkStatus() const {
  return (IsUp(state_) ? UCIE_LINK_STATUS_UP : 0) |
         (IsTraining(state_) ? UCIE_LINK_STATUS_TRAINING : 0) |
         (status_changed_ ? UCIE_LINK_STATUS_CHANGED : 0) |
         (fatal_ ? UCIE_LINK_STATUS_UNCORRECTABLE_FATAL : 0);
}

bool UcieLinkRegisters::Interrupting() const {
  return status_changed_ && status_changed_interrupt_;
}

}  // namespace socpuppet
