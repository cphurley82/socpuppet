#ifndef SOCPUPPET_CORE_I2C_CONTROLLER_LOGIC_H_
#define SOCPUPPET_CORE_I2C_CONTROLLER_LOGIC_H_

#include <array>
#include <cstdint>
#include <span>

#include "socpuppet/core/i2c_device.h"

namespace socpuppet {

// What an I2C controller does, with no simulator attached: the registers
// of the OpenCores I2C master core (regs/i2c_controller.rdl), and the
// commands it carries out on its bus.
class I2cControllerLogic {
 public:
  // Reads and writes of the register block. Each returns false, and
  // changes nothing, if the access is refused.
  //
  // 🎓 Each register is a byte, at the bottom of a 32-bit word of its own:
  // a driver may read or write the byte alone, or the whole word.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const;
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in);

  // Puts `device` on the bus at `address`, seven bits. It is not owned,
  // and must outlive the controller's use of it.
  void Attach(std::uint8_t address, I2cDevice& device) {
    devices_.at(address) = &device;
  }

  // Whether a command written to the controller waits to be carried out:
  // the status's transfer in progress.
  bool CommandWaiting() const { return command_ != 0; }

  // How many of the controller's clock cycles a command takes on the bus:
  // a byte and its acknowledgement, nine of the bus's clocks, each five
  // times one more than the prescale.
  std::uint64_t CommandCycles() const;

  // Carries out the command that waits, on the bus, if one does: the calls
  // to the devices it makes are all here, for whoever has the time to make
  // them.
  void CarryOut();

  // Whether the controller's interrupt is up: a command is done, and the
  // interrupt is enabled and not yet cleared.
  bool Interrupting() const;

 private:
  // The status register, as it reads.
  std::uint8_t Status() const;

  std::uint8_t prescale_low_ = 0xFF;
  std::uint8_t prescale_high_ = 0xFF;
  std::uint8_t control_ = 0;
  std::uint8_t transmit_ = 0;
  std::uint8_t receive_ = 0;
  // The command that waits to be carried out, or 0.
  std::uint8_t command_ = 0;
  bool interrupt_ = false;
  bool no_ack_ = false;
  // The device the last start addressed, if it acknowledged; until a stop.
  I2cDevice* addressed_ = nullptr;
  bool busy_ = false;
  // The devices on the bus, by their seven-bit address.
  std::array<I2cDevice*, 128> devices_{};
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_I2C_CONTROLLER_LOGIC_H_
