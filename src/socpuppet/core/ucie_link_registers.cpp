#include "socpuppet/core/ucie_link_registers.h"

#include <cstdint>
#include <span>
#include <utility>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/ucie_link_state.h"

namespace socpuppet {
namespace {

// PCIe's identifier for a designated vendor-specific extended capability,
// and the identifier UCIe registered as a vendor.
constexpr std::uint32_t kDvsecCapabilityId = 0x0023;
constexpr std::uint32_t kUcieVendorId = 0xD2DE;

constexpr std::size_t kRegisterBytes = 4;

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
  if (out.size() != kRegisterBytes || offset > kSize - kRegisterBytes) {
    return false;
  }
  StoreLittleEndian(RegisterAt(offset), out);
  return true;
}

bool UcieLinkRegisters::WriteRegister(std::uint64_t offset,
                                      std::span<const std::uint8_t> in) {
  if (in.size() != kRegisterBytes || offset > kSize - kRegisterBytes) {
    return false;
  }
  return Set(offset, LoadLittleEndian<std::uint32_t>(in));
}

std::uint32_t UcieLinkRegisters::RegisterAt(std::uint64_t offset) const {
  switch (offset) {
    case kExtendedCapabilityHeader:
      // The capability's identifier, its version, and the offset of the
      // next capability, of which there is none.
      return kDvsecCapabilityId | (1U << 16);
    case kDvsecHeader1:
      // Whose capability it is, its revision, and how long it is.
      return kUcieVendorId | (static_cast<std::uint32_t>(kSize) << 20);
    case kDvsecHeader2:
      // Which of the vendor's capabilities it is. UCIe's own number for
      // the link DVSEC is not in public sources, so this is ours.
      return 0x0001;
    case kLinkStatusRegister:
      return LinkStatus();
    case kNotification:
      return status_changed_interrupt_ ? kStatusChangedInterrupt : 0;
    case kRegisterLocator:
      // Where the block of the link's own registers is, and which block
      // it is. UCIe says a locator points at a block of registers; what
      // one looks like is not in public sources, so this is ours: the
      // offset from the start of the capability, and a block number.
      return static_cast<std::uint32_t>(kLinkTrainingStateRegister << 8) | 1U;
    case kLinkTrainingStateRegister:
      return static_cast<std::uint32_t>(state_);
    case kDieReset:
      return reset_ ? 1U : 0U;
    case kMailboxOpcode:
      return static_cast<std::uint32_t>(mailbox_.opcode);
    case kMailboxAddress:
      return mailbox_.address;
    case kMailboxData:
      return answer_;
    case kMailboxStatus:
      return static_cast<std::uint32_t>(answer_status_) |
             (mailbox_busy_ ? kMailboxBusy : 0);
    default:
      // Including link control, fault injection and the mailbox trigger,
      // which are actions and read back as nothing to do.
      return 0;
  }
}

bool UcieLinkRegisters::Set(std::uint64_t offset, std::uint32_t value) {
  switch (offset) {
    case kLinkControl:
      if ((value & kStartTraining) != 0) asked_.start_training = true;
      if ((value & kRetrainLink) != 0) asked_.retrain = true;
      return true;
    case kLinkStatusRegister:
      // The bits that say something happened are cleared by writing a one
      // to them, so that firmware cannot lose one it has not seen.
      if ((value & kLinkStatusChanged) != 0) status_changed_ = false;
      if ((value & kDetectedUncorrectableFatal) != 0) fatal_ = false;
      return true;
    case kNotification:
      status_changed_interrupt_ = (value & kStatusChangedInterrupt) != 0;
      return true;
    case kDieReset:
      reset_ = (value & 1U) != 0;
      return true;
    case kFaultInjection:
      if ((value & 1U) != 0) asked_.fault = true;
      return true;
    case kMailboxOpcode:
      mailbox_.opcode = static_cast<SidebandOpcode>(value & 0x1FU);
      return true;
    case kMailboxAddress:
      mailbox_.address = value;
      return true;
    case kMailboxData:
      mailbox_.data = value;
      return true;
    case kMailboxTrigger:
      if ((value & 1U) != 0) {
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
  return (IsUp(state_) ? kLinkUp : 0) |
         (IsTraining(state_) ? kLinkTraining : 0) |
         (status_changed_ ? kLinkStatusChanged : 0) |
         (fatal_ ? kDetectedUncorrectableFatal : 0);
}

bool UcieLinkRegisters::Interrupting() const {
  return status_changed_ && status_changed_interrupt_;
}

}  // namespace socpuppet
