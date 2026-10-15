#ifndef SOCPUPPET_CORE_SYSTEM_CONTROLLER_LOGIC_H_
#define SOCPUPPET_CORE_SYSTEM_CONTROLLER_LOGIC_H_

#include <cstddef>
#include <cstdint>
#include <span>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/regs/system_controller.h"

namespace socpuppet {

// What a CPU's system controller does, with no simulator attached: the
// registers its CPU reads (regs/system_controller.rdl), and its CPU's
// reset.
//
// The reset has three masters. Something may hold the CPU until it is
// ready for it, as a die-to-die link does until it is trained. A watchdog
// bites when firmware stops feeding it. And firmware may ask. A hold lasts
// as long as its line is high. The other two are pulses: the reset rises,
// and whoever owns the clock says when the pulse has been long enough.
// Firmware may also switch its CPU off, which holds it in reset for good.
class SystemControllerLogic {
 public:
  // `die` and `boot_address` are what the two registers of those names
  // read: which die the CPU is on, and where its boot ROM finds its image.
  SystemControllerLogic(std::uint32_t die, std::uint32_t boot_address)
      : die_(die), boot_address_(boot_address) {}

  // Reads and writes of the register block, by the CPU. Each returns
  // false, and changes nothing, if the access is refused: it is not of one
  // whole register, or it writes a register that is not firmware's to
  // write.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const {
    if (out.size() != kRegisterBytes) return false;
    switch (offset) {
      case SYSTEM_CONTROLLER_DIE:
        StoreLittleEndian(die_, out);
        return true;
      case SYSTEM_CONTROLLER_BOOT_ADDRESS:
        StoreLittleEndian(boot_address_, out);
        return true;
      case SYSTEM_CONTROLLER_RESET_CAUSE:
        StoreLittleEndian(cause_, out);
        return true;
      case SYSTEM_CONTROLLER_RESET_REQUEST:
        StoreLittleEndian(std::uint32_t{0}, out);
        return true;
      case SYSTEM_CONTROLLER_POWER_OFF:
        StoreLittleEndian(off_ ? SYSTEM_CONTROLLER_POWER_OFF_OFF : 0U, out);
        return true;
      default:
        return false;
    }
  }

  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in) {
    if (in.size() != kRegisterBytes) return false;
    const auto value = LoadLittleEndian<std::uint32_t>(in);
    switch (offset) {
      case SYSTEM_CONTROLLER_RESET_REQUEST:
        if ((value & SYSTEM_CONTROLLER_RESET_REQUEST_RESET) != 0) {
          Pulse(SYSTEM_CONTROLLER_RESET_CAUSE_SOFTWARE);
        }
        return true;
      case SYSTEM_CONTROLLER_POWER_OFF:
        // Once off, the CPU stays off: nothing here switches it on again.
        if ((value & SYSTEM_CONTROLLER_POWER_OFF_OFF) != 0) off_ = true;
        return true;
      default:
        return false;
    }
  }

  // The line that holds the CPU in reset for as long as it is high.
  void Hold(bool held) { held_ = held; }

  // The watchdog's line has risen.
  void Bite() { Pulse(SYSTEM_CONTROLLER_RESET_CAUSE_WATCHDOG); }

  // A pulse has lasted long enough for the CPU to have seen it.
  void EndPulse() { pulsing_ = false; }

  // Whether a pulse is under way: someone has to end it.
  bool Pulsing() const { return pulsing_; }

  // What the CPU's reset line is to be.
  bool Reset() const { return held_ || pulsing_ || off_; }

 private:
  // Each register is 32 bits wide.
  static constexpr std::size_t kRegisterBytes = 4;

  void Pulse(std::uint32_t cause) {
    pulsing_ = true;
    cause_ = cause;
  }

  std::uint32_t die_;
  std::uint32_t boot_address_;
  std::uint32_t cause_ = SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON;
  bool held_ = false;
  bool pulsing_ = false;
  bool off_ = false;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_SYSTEM_CONTROLLER_LOGIC_H_
