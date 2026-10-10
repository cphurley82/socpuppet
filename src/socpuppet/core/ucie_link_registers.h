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
// a further block of registers is. That block, and the sideband mailbox
// after it, are ours.
//
// Where each register is, what its bits are and what it holds at reset
// are in the link's register map, regs/ucie_link.rdl, and this class and
// everything that drives it go by the names generated from that
// (socpuppet/regs/ucie_link.h). docs/models/d2d-link.md has the table.
//
// Every access is 32 bits wide. A register inside the block that this
// model has nothing for reads as zero. The registers themselves do
// nothing: what firmware asks for by writing them is picked up with
// TakeCommands(), and what the link is doing is put in with LinkIs().
// D2dLinkLogic is what joins the two.
class UcieLinkRegisters {
 public:
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
