#ifndef SOCPUPPET_CORE_UCIE_LINK_REGISTERS_H_
#define SOCPUPPET_CORE_UCIE_LINK_REGISTERS_H_

#include <cstdint>
#include <optional>
#include <span>

#include "socpuppet/core/ucie_link_state.h"
#include "socpuppet/core/ucie_sideband.h"

namespace socpuppet {

// A register access for the other die, as firmware has filled the mailbox
// in. The address is an offset into the other end's own register block,
// and a whole 32-bit register is read or written.
struct MailboxRequest {
  SidebandOpcode opcode{};
  std::uint32_t address = 0;
  std::uint32_t data = 0;

  bool operator==(const MailboxRequest&) const = default;
};

// The registers one end of a die-to-die link shows the firmware on its own
// die, and that the other die can reach over the sideband.
//
// They are UCIe's Link DVSEC, a designated vendor-specific extended
// capability of the kind PCIe defines, at a fixed place in memory rather
// than in a configuration space: three header registers that say whose
// capability it is, then link control, link status and the control over
// what the link interrupts about, then a register locator that says where
// a further block of registers is.
//
//   0x00  extended capability header   0x1C  register locator
//   0x04  DVSEC header 1 (vendor)      0x20  link training state
//   0x08  DVSEC header 2 (id)          0x24  reset control
//   0x10  link control                 0x28  fault injection
//   0x14  link status                  0x40  the sideband mailbox
//   0x18  link event notification
//
// UCIe's capability has a link capability register at 0x0C as well, which
// says what the link can do. Nothing here reads one, so it is not
// modelled: it reads as zero, as any register in the block that this model
// has nothing for does.
//
// The block from 0x20 is ours: UCIe has a register locator and says the
// capability's own registers are vendor-defined, so what is in it here is
// what this model needs. So is the sideband mailbox's layout, which UCIe
// has and whose fields are not in public sources.
//
// Every access is 32 bits wide. The registers themselves do nothing: what
// firmware asks for by writing them is picked up with TakeCommands(), and
// what the link is doing is put in with LinkIs(). D2dLinkLogic is what
// joins the two.
class UcieLinkRegisters {
 public:
  // How much room the block takes. A register inside it that this model
  // has nothing for reads as zero.
  static constexpr std::uint64_t kSize = 0x100;

  // Where each register is. Firmware on this die, the other die's mailbox
  // and the drivers above all go by these.
  static constexpr std::uint64_t kExtendedCapabilityHeader = 0x00;
  static constexpr std::uint64_t kDvsecHeader1 = 0x04;
  static constexpr std::uint64_t kDvsecHeader2 = 0x08;
  static constexpr std::uint64_t kLinkControl = 0x10;
  static constexpr std::uint64_t kLinkStatusRegister = 0x14;
  static constexpr std::uint64_t kNotification = 0x18;
  static constexpr std::uint64_t kRegisterLocator = 0x1C;
  // The block the locator points at, which is ours.
  static constexpr std::uint64_t kLinkTrainingStateRegister = 0x20;
  static constexpr std::uint64_t kDieReset = 0x24;
  static constexpr std::uint64_t kFaultInjection = 0x28;
  // The mailbox, also ours.
  static constexpr std::uint64_t kMailboxOpcode = 0x40;
  static constexpr std::uint64_t kMailboxAddress = 0x48;
  static constexpr std::uint64_t kMailboxData = 0x50;
  static constexpr std::uint64_t kMailboxTrigger = 0x58;
  static constexpr std::uint64_t kMailboxStatus = 0x5C;

  // Link control, which firmware writes. Both bits clear themselves: they
  // are an action, not a setting.
  static constexpr std::uint32_t kStartTraining = 1U << 0;
  static constexpr std::uint32_t kRetrainLink = 1U << 1;
  // Link status.
  static constexpr std::uint32_t kLinkUp = 1U << 0;
  static constexpr std::uint32_t kLinkTraining = 1U << 1;
  static constexpr std::uint32_t kLinkStatusChanged = 1U << 2;
  static constexpr std::uint32_t kDetectedUncorrectableFatal = 1U << 3;
  // Link event notification.
  static constexpr std::uint32_t kStatusChangedInterrupt = 1U << 0;
  // The mailbox's status: how the last access turned out, and whether
  // there is an access still waiting to be answered.
  static constexpr std::uint32_t kMailboxStatusCode = 0x7;
  static constexpr std::uint32_t kMailboxBusy = 1U << 8;

  // What firmware has asked for by writing to the registers, which it is
  // given only once.
  struct Commands {
    bool start_training = false;
    bool retrain = false;
    bool fault = false;
    std::optional<MailboxRequest> mailbox;
  };

  // A read or a write by firmware on this die, or by the other die over
  // the sideband. Each returns false, and changes nothing, if the access
  // is refused: it is not 32 bits wide, it starts outside the block, or it
  // writes a register that is not firmware's to write.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const;
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in);

  Commands TakeCommands();

  // What the link is doing now. The status-changed bit is set when the
  // link goes up or comes down, which is what firmware is interrupted
  // about.
  void LinkIs(LinkTrainingState state);
  // The other die has reported an error nothing can be done about.
  void FatalReported();
  // The register access firmware asked the other die for has been
  // answered.
  void MailboxAnswered(SidebandStatus status, std::uint32_t data);

  // Whether the reset line this end drives on its own die is held. That
  // is the die's CPU on the compute side of M5's board, and nothing at
  // all on the manager side; the manager lets the compute die go by
  // writing this register of the other end over the sideband.
  bool ResetAsserted() const { return reset_; }
  // Whether the link is asking for its firmware's attention.
  bool Interrupting() const;

 private:
  std::uint32_t LinkStatus() const;
  std::uint32_t RegisterAt(std::uint64_t offset) const;
  bool Set(std::uint64_t offset, std::uint32_t value);

  LinkTrainingState state_ = LinkTrainingState::kReset;
  bool link_was_up_ = false;
  bool status_changed_ = false;
  bool fatal_ = false;
  bool status_changed_interrupt_ = false;
  // A die comes out of reset only when something lets it.
  bool reset_ = true;
  Commands asked_;
  // What firmware has put in the mailbox, whether it is still waiting to
  // be answered, and what came back.
  MailboxRequest mailbox_;
  bool mailbox_busy_ = false;
  std::uint32_t answer_ = 0;
  SidebandStatus answer_status_ = SidebandStatus::kSuccess;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_UCIE_LINK_REGISTERS_H_
