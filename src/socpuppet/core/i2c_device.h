#ifndef SOCPUPPET_CORE_I2C_DEVICE_H_
#define SOCPUPPET_CORE_I2C_DEVICE_H_

#include <cstdint>

namespace socpuppet {

// A device on an I2C bus, as its controller sees it.
//
// 🎓 I2C is a bus of two wires, a clock and a data line, which many chips
// share. The controller starts a transfer and sends an address, seven
// bits that pick one device, and a bit for the direction. Then bytes go
// one way or the other, each acknowledged by whoever received it: a
// device that does not acknowledge its address is not there, or is busy.
// A stop ends the transfer, and a start before it starts another at once:
// a device that a start addresses another device after hears no Stop(),
// and is not addressed again until a start names it.
//
// The controller calls a device from a thread process of its own, so a
// device may wait in any call. 🎓 Time it waits is time added to the
// transfer, as a real device holds the clock low until it is ready
// (clock stretching).
class I2cDevice {
 public:
  virtual ~I2cDevice() = default;

  // A start, and this device's address: `read` says which way the bytes
  // go. Returns whether the device acknowledges.
  virtual bool Start(bool read) = 0;

  // A byte from the controller. Returns whether the device acknowledges.
  virtual bool Write(std::uint8_t byte) = 0;

  // A byte to the controller. `last` says the controller will not
  // acknowledge it, which ends the read.
  virtual std::uint8_t Read(bool last) = 0;

  // A stop: the transfer is over.
  virtual void Stop() = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_I2C_DEVICE_H_
