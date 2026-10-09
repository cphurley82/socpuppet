#ifndef SOCPUPPET_CORE_COMMAND_STATUS_H_
#define SOCPUPPET_CORE_COMMAND_STATUS_H_

#include <cstdint>

namespace socpuppet {

// The status register of a device that is given one command at a time by
// its CPU, and its interrupt-enable register beside it.
//
// The status has three bits. BUSY is set from when a command is given
// until it has been carried out, and then DONE or ERROR says how it went.
// A device takes no command while it is busy: that is the device's to
// refuse, by asking Busy() first.
// Giving the next command forgets how the last one went, so the status is
// always about the last command. The CPU clears DONE or ERROR by writing a
// one to it, and cannot clear BUSY. The device interrupts while a bit the
// CPU has enabled is set.
class CommandStatus {
 public:
  static constexpr std::uint32_t kDone = 1U << 0;
  static constexpr std::uint32_t kError = 1U << 1;
  static constexpr std::uint32_t kBusy = 1U << 2;

  // The device has been given a command.
  void Start() { status_ = kBusy; }
  // The device has carried the command out, or could not.
  void Finish(bool carried_out) { status_ = carried_out ? kDone : kError; }

  // Whether a command has been given and not yet carried out.
  bool Busy() const { return (status_ & kBusy) != 0; }

  // The registers, as the CPU reads and writes them.
  std::uint32_t Status() const { return status_; }
  void WriteStatus(std::uint32_t ones_to_clear) {
    status_ &= ~(ones_to_clear & kCanInterrupt);
  }
  std::uint32_t InterruptEnable() const { return interrupt_enable_; }
  void WriteInterruptEnable(std::uint32_t bits) {
    interrupt_enable_ = bits & kCanInterrupt;
  }

  // Whether the device is asking for its CPU's attention.
  bool Interrupting() const { return (status_ & interrupt_enable_) != 0; }

 private:
  // The bits the CPU may clear, and may be interrupted by.
  static constexpr std::uint32_t kCanInterrupt = kDone | kError;

  std::uint32_t status_ = 0;
  std::uint32_t interrupt_enable_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_COMMAND_STATUS_H_
