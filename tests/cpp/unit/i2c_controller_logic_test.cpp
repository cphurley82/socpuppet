#include "socpuppet/core/i2c_controller_logic.h"

#include <array>
#include <cstdint>
#include <format>
#include <span>
#include <string>
#include <vector>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/regs/i2c_controller.h"

namespace socpuppet {

namespace {

// The address of the device the tests talk to, seven bits.
constexpr std::uint8_t kAddress = 0x51;
// 🎓 The byte after a start: the address, and the direction in bit 0.
constexpr std::uint8_t kWriteToTheDevice = kAddress << 1;
constexpr std::uint8_t kReadFromTheDevice = kAddress << 1 | 1;
// A byte of data.
constexpr std::uint8_t kByte = 0xA5;

// A device on the bus that notes each call, as words, and answers as it
// is told.
struct RecordingDevice : I2cDevice {
  bool Start(bool read) override {
    calls.push_back(read ? "start read" : "start write");
    return acknowledges;
  }
  bool Write(std::uint8_t byte) override {
    calls.push_back(std::format("write {:#04x}", byte));
    return acknowledges;
  }
  std::uint8_t Read(bool last) override {
    calls.push_back(last ? "read last" : "read");
    return answer;
  }
  void Stop() override { calls.push_back("stop"); }

  bool acknowledges = true;
  std::uint8_t answer = 0;
  std::vector<std::string> calls;
};

// A whole register, as a driver that reads 32 bits at a time sees it.
std::uint32_t Read32(const I2cControllerLogic& controller,
                     std::uint64_t offset) {
  std::array<std::uint8_t, 4> out{};
  EXPECT_TRUE(controller.ReadRegister(offset, out));
  return LoadLittleEndian<std::uint32_t>(out);
}

void Write32(I2cControllerLogic& controller, std::uint64_t offset,
             std::uint32_t value) {
  std::array<std::uint8_t, 4> in{};
  StoreLittleEndian(value, in);
  EXPECT_TRUE(controller.WriteRegister(offset, in));
}

// Gives the controller `command`, with `byte` to send, as a driver does.
void Issue(I2cControllerLogic& controller, std::uint32_t command,
           std::uint8_t byte = 0) {
  Write32(controller, I2C_CONTROLLER_TRANSMIT, byte);
  Write32(controller, I2C_CONTROLLER_COMMAND, command);
}

// A controller with `device` at kAddress, switched on unless told not to.
struct OnTheBus {
  explicit OnTheBus(RecordingDevice& device, bool on = true) {
    controller.Attach(kAddress, device);
    if (on) Control(I2C_CONTROLLER_CONTROL_ENABLE);
  }

  void Control(std::uint32_t control) {
    Write32(controller, I2C_CONTROLLER_CONTROL, control);
  }

  void EnableTheInterrupt() {
    Control(I2C_CONTROLLER_CONTROL_ENABLE |
            I2C_CONTROLLER_CONTROL_INTERRUPT_ENABLE);
  }

  // Issues `command` and has it carried out, as the bus's time does.
  // Returns the status after.
  std::uint32_t Do(std::uint32_t command, std::uint8_t byte = 0) {
    Issue(controller, command, byte);
    controller.CarryOut();
    return Read32(controller, I2C_CONTROLLER_STATUS);
  }

  std::uint32_t Start(std::uint8_t address_and_direction) {
    return Do(I2C_CONTROLLER_COMMAND_START | I2C_CONTROLLER_COMMAND_WRITE,
              address_and_direction);
  }

  I2cControllerLogic controller;
};

TEST(AnI2cControllerOutOfReset, HasTheLargestPrescaleAndNothingInItsStatus) {
  const I2cControllerLogic controller;

  EXPECT_EQ(Read32(controller, I2C_CONTROLLER_PRESCALE_LOW), 0xFFU);
  EXPECT_EQ(Read32(controller, I2C_CONTROLLER_PRESCALE_HIGH), 0xFFU);
  EXPECT_EQ(Read32(controller, I2C_CONTROLLER_STATUS), 0U);
}

// Zephyr's i2c_sifive reads and writes each register a byte at a time.
TEST(AnI2cControllersRegister, IsReadAndWrittenAByteAtATimeToo) {
  I2cControllerLogic controller;
  const std::array<std::uint8_t, 1> written{0x2A};
  std::array<std::uint8_t, 1> read{};

  ASSERT_TRUE(controller.WriteRegister(I2C_CONTROLLER_PRESCALE_LOW, written));
  ASSERT_TRUE(controller.ReadRegister(I2C_CONTROLLER_PRESCALE_LOW, read));

  EXPECT_EQ(read[0], 0x2A);
}

TEST(AnI2cControllerThatIsOff, TakesNoCommand) {
  RecordingDevice device;
  OnTheBus bus{device, /*on=*/false};

  Issue(bus.controller,
        I2C_CONTROLLER_COMMAND_START | I2C_CONTROLLER_COMMAND_WRITE,
        kWriteToTheDevice);
  bus.controller.CarryOut();

  EXPECT_FALSE(bus.controller.CommandWaiting());
  EXPECT_TRUE(device.calls.empty());
}

// The driver polls the status for it.
TEST(AnI2cCommand, IsInProgressUntilItIsCarriedOut) {
  RecordingDevice device;
  OnTheBus bus{device};

  Issue(bus.controller,
        I2C_CONTROLLER_COMMAND_START | I2C_CONTROLLER_COMMAND_WRITE,
        kWriteToTheDevice);

  EXPECT_TRUE(Read32(bus.controller, I2C_CONTROLLER_STATUS) &
              I2C_CONTROLLER_STATUS_TRANSFER_IN_PROGRESS);
  EXPECT_TRUE(device.calls.empty());
}

// The wrapper asks, to know when to carry it out.
TEST(AnI2cCommand, WaitsUntilItIsCarriedOut) {
  RecordingDevice device;
  OnTheBus bus{device};

  Issue(bus.controller,
        I2C_CONTROLLER_COMMAND_START | I2C_CONTROLLER_COMMAND_WRITE,
        kWriteToTheDevice);
  const bool waiting = bus.controller.CommandWaiting();
  bus.controller.CarryOut();

  EXPECT_TRUE(waiting);
  EXPECT_FALSE(bus.controller.CommandWaiting());
}

TEST(AStartWithAWriteAddress, ReachesTheDeviceThereForAWrite) {
  RecordingDevice device;
  OnTheBus bus{device};

  const std::uint32_t status = bus.Start(kWriteToTheDevice);

  EXPECT_EQ(device.calls, std::vector<std::string>{"start write"});
  EXPECT_FALSE(status & I2C_CONTROLLER_STATUS_NO_ACK);
}

TEST(AStartWithAReadAddress, ReachesTheDeviceThereForARead) {
  RecordingDevice device;
  OnTheBus bus{device};

  const std::uint32_t status = bus.Start(kReadFromTheDevice);

  EXPECT_EQ(device.calls, std::vector<std::string>{"start read"});
  EXPECT_FALSE(status & I2C_CONTROLLER_STATUS_NO_ACK);
}

TEST(AStart, MakesTheBusBusy) {
  RecordingDevice device;
  OnTheBus bus{device};

  const std::uint32_t status = bus.Start(kWriteToTheDevice);

  EXPECT_TRUE(status & I2C_CONTROLLER_STATUS_BUSY);
}

TEST(AStartWithAnAddressNoDeviceHas, IsNotAcknowledged) {
  RecordingDevice device;
  OnTheBus bus{device};

  const std::uint32_t status = bus.Start((kAddress + 1) << 1);

  EXPECT_TRUE(device.calls.empty());
  EXPECT_TRUE(status & I2C_CONTROLLER_STATUS_NO_ACK);
}

TEST(AWriteAfterAStart, SendsTheByteToTheAddressedDevice) {
  RecordingDevice device;
  OnTheBus bus{device};
  bus.Start(kWriteToTheDevice);

  bus.Do(I2C_CONTROLLER_COMMAND_WRITE, kByte);

  EXPECT_EQ(device.calls,
            (std::vector<std::string>{"start write", "write 0xa5"}));
}

TEST(AWriteTheDeviceDoesNotAcknowledge, SaysSoInTheStatus) {
  RecordingDevice device;
  OnTheBus bus{device};
  bus.Start(kWriteToTheDevice);
  device.acknowledges = false;

  const std::uint32_t status = bus.Do(I2C_CONTROLLER_COMMAND_WRITE, kByte);

  EXPECT_TRUE(status & I2C_CONTROLLER_STATUS_NO_ACK);
}

TEST(AReadAfterAStart, ReceivesTheDevicesByte) {
  RecordingDevice device;
  OnTheBus bus{device};
  bus.Start(kReadFromTheDevice);
  device.answer = kByte;

  bus.Do(I2C_CONTROLLER_COMMAND_READ);

  EXPECT_EQ(Read32(bus.controller, I2C_CONTROLLER_RECEIVE), kByte);
}

TEST(AReadWithNack, IsTheDevicesLast) {
  RecordingDevice device;
  OnTheBus bus{device};
  bus.Start(kReadFromTheDevice);

  bus.Do(I2C_CONTROLLER_COMMAND_READ | I2C_CONTROLLER_COMMAND_NACK);

  EXPECT_EQ(device.calls,
            (std::vector<std::string>{"start read", "read last"}));
}

TEST(AStopAfterAByte, EndsTheTransferAndTheDeviceHearsIt) {
  RecordingDevice device;
  OnTheBus bus{device};
  bus.Start(kWriteToTheDevice);

  const std::uint32_t status =
      bus.Do(I2C_CONTROLLER_COMMAND_WRITE | I2C_CONTROLLER_COMMAND_STOP, kByte);

  EXPECT_EQ(device.calls,
            (std::vector<std::string>{"start write", "write 0xa5", "stop"}));
  EXPECT_FALSE(status & I2C_CONTROLLER_STATUS_BUSY);
}

TEST(AnI2cControllersInterrupt, IsUpOnceACommandIsDoneUntilItIsCleared) {
  RecordingDevice device;
  OnTheBus bus{device};
  bus.EnableTheInterrupt();

  bus.Start(kWriteToTheDevice);
  const bool done = bus.controller.Interrupting();
  bus.Do(I2C_CONTROLLER_COMMAND_CLEAR_INTERRUPT);

  EXPECT_TRUE(done);
  EXPECT_FALSE(bus.controller.Interrupting());
}

TEST(AnI2cControllersInterruptNotEnabled, StaysDownWhenACommandIsDone) {
  RecordingDevice device;
  OnTheBus bus{device};

  bus.Start(kWriteToTheDevice);

  EXPECT_FALSE(bus.controller.Interrupting());
}

// 🎓 A byte and its acknowledgement are nine of the bus's clocks, and the
// bus's clock is the controller's over five times one more than the
// prescale: (f / (5 (prescale + 1))), which is how a driver sets it.
TEST(AnI2cCommand, TakesNineOfTheBusesClocksInTheControllersCycles) {
  RecordingDevice device;
  OnTheBus bus{device};
  Write32(bus.controller, I2C_CONTROLLER_PRESCALE_LOW, 0x02);
  Write32(bus.controller, I2C_CONTROLLER_PRESCALE_HIGH, 0x01);

  EXPECT_EQ(bus.controller.CommandCycles(), 9U * 5U * (0x0102U + 1U));
}

}  // namespace

}  // namespace socpuppet
