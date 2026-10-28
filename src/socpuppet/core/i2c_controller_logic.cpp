#include "socpuppet/core/i2c_controller_logic.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>

#include "socpuppet/core/i2c_device.h"
#include "socpuppet/regs/i2c_controller.h"

namespace socpuppet {

namespace {

// Whether an access of `bytes` reaches a register's byte: the byte alone,
// or the whole word it is the bottom of.
bool OfARegister(std::size_t bytes) { return bytes == 1 || bytes == 4; }

// The bus's clocks a command takes: a byte, and its acknowledgement.
constexpr std::uint64_t kClocksOfAByte = 9;
// 🎓 The OpenCores core's bus clock is five of the prescaled clock's.
constexpr std::uint64_t kPrescaledClocksOfABusClock = 5;
// 🎓 The byte after a start is the address, in its top seven bits, and the
// direction, in its bottom one: a one is a read.
constexpr std::uint8_t kRead = 1;

}  // namespace

bool I2cControllerLogic::ReadRegister(std::uint64_t offset,
                                      std::span<std::uint8_t> out) const {
  if (!OfARegister(out.size())) return false;
  std::uint8_t value = 0;
  switch (offset) {
    case I2C_CONTROLLER_PRESCALE_LOW:
      value = prescale_low_;
      break;
    case I2C_CONTROLLER_PRESCALE_HIGH:
      value = prescale_high_;
      break;
    case I2C_CONTROLLER_CONTROL:
      value = control_;
      break;
    case I2C_CONTROLLER_RECEIVE:
      value = receive_;
      break;
    case I2C_CONTROLLER_STATUS:
      value = Status();
      break;
    default:
      return false;
  }
  std::ranges::fill(out, std::uint8_t{0});
  out[0] = value;
  return true;
}

bool I2cControllerLogic::WriteRegister(std::uint64_t offset,
                                       std::span<const std::uint8_t> in) {
  if (!OfARegister(in.size())) return false;
  const std::uint8_t value = in[0];
  switch (offset) {
    case I2C_CONTROLLER_PRESCALE_LOW:
      prescale_low_ = value;
      return true;
    case I2C_CONTROLLER_PRESCALE_HIGH:
      prescale_high_ = value;
      return true;
    case I2C_CONTROLLER_CONTROL:
      control_ = value;
      return true;
    case I2C_CONTROLLER_TRANSMIT:
      transmit_ = value;
      return true;
    case I2C_CONTROLLER_COMMAND:
      // The OpenCores core ignores a command while it is off.
      if ((control_ & I2C_CONTROLLER_CONTROL_ENABLE) == 0) return true;
      if ((value & I2C_CONTROLLER_COMMAND_CLEAR_INTERRUPT) != 0) {
        interrupt_ = false;
      }
      command_ = value & static_cast<std::uint8_t>(
                             ~I2C_CONTROLLER_COMMAND_CLEAR_INTERRUPT);
      return true;
    default:
      return false;
  }
}

std::uint64_t I2cControllerLogic::CommandCycles() const {
  const std::uint64_t prescale =
      static_cast<std::uint64_t>(prescale_high_) << 8 | prescale_low_;
  return kClocksOfAByte * kPrescaledClocksOfABusClock * (prescale + 1);
}

void I2cControllerLogic::CarryOut() {
  const std::uint8_t command = command_;
  command_ = 0;
  if (command == 0) return;
  if ((command & I2C_CONTROLLER_COMMAND_START) != 0) {
    I2cDevice* device = devices_[transmit_ >> 1];
    const bool read = (transmit_ & kRead) != 0;
    busy_ = true;
    addressed_ = device != nullptr && device->Start(read) ? device : nullptr;
    no_ack_ = addressed_ == nullptr;
  } else if ((command & I2C_CONTROLLER_COMMAND_WRITE) != 0) {
    no_ack_ = addressed_ == nullptr || !addressed_->Write(transmit_);
  } else if ((command & I2C_CONTROLLER_COMMAND_READ) != 0) {
    const bool last = (command & I2C_CONTROLLER_COMMAND_NACK) != 0;
    // Nobody drives the line: it reads as ones.
    receive_ = addressed_ != nullptr ? addressed_->Read(last) : 0xFF;
  }
  if ((command & I2C_CONTROLLER_COMMAND_STOP) != 0) {
    if (addressed_ != nullptr) addressed_->Stop();
    addressed_ = nullptr;
    busy_ = false;
  }
  interrupt_ = true;
}

bool I2cControllerLogic::Interrupting() const {
  return interrupt_ &&
         (control_ & I2C_CONTROLLER_CONTROL_INTERRUPT_ENABLE) != 0;
}

std::uint8_t I2cControllerLogic::Status() const {
  std::uint8_t status = 0;
  if (interrupt_) status |= I2C_CONTROLLER_STATUS_INTERRUPT;
  if (CommandWaiting()) status |= I2C_CONTROLLER_STATUS_TRANSFER_IN_PROGRESS;
  if (busy_) status |= I2C_CONTROLLER_STATUS_BUSY;
  if (no_ack_) status |= I2C_CONTROLLER_STATUS_NO_ACK;
  return status;
}

}  // namespace socpuppet
