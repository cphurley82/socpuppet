#include "socpuppet/models/i2c_controller.h"

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>

#include "socpuppet/core/i2c_device.h"
#include "socpuppet/regs/i2c_controller.h"
#include "tests/cpp/support/bus_driver.h"

// What socpuppet relies on of its I2C controller in a simulation: when a
// command is carried out on the bus, from where, and its interrupt. What
// the registers and the commands mean is held in
// tests/cpp/unit/i2c_controller_logic_test.cpp.

namespace {

constexpr std::uint8_t kAddress = 0x51;
// The controller's clock, and the prescale that makes the bus's 100 kHz
// of it: 50 MHz / (5 (99 + 1)).
constexpr std::uint64_t kFiftyMegahertz = 50'000'000;
constexpr std::uint32_t kPrescaleForOneHundredKilohertz = 99;
// Nine of the bus's clocks at 100 kHz: a byte and its acknowledgement.
sc_core::sc_time AByteOnTheBus() { return {90, sc_core::SC_US}; }

// A device on the bus that notes when a start reaches it, and from which
// process.
struct TimingDevice : socpuppet::I2cDevice {
  bool Start(bool /*read*/) override {
    started_at = sc_core::sc_time_stamp();
    const sc_core::sc_process_handle process =
        sc_core::sc_get_current_process_handle();
    caller = process.name();
    caller_kind = process.proc_kind();
    return true;
  }
  bool Write(std::uint8_t /*byte*/) override { return true; }
  std::uint8_t Read(bool /*last*/) override { return 0; }
  void Stop() override {}

  sc_core::sc_time started_at;
  std::string caller;
  sc_core::sc_curr_proc_kind caller_kind = sc_core::SC_NO_PROC_;
};

// A controller with `device` at kAddress, a test's thread at its
// registers, and its interrupt line.
//
// `line`, if given, is pointed at the interrupt line before the run, for a
// test's thread to look at.
struct Rig {
  Rig(socpuppet::I2cDevice& device,
      const std::function<void(BusDriver&)>& at_the_registers,
      sc_core::sc_signal<bool>** line = nullptr)
      : registers{"registers", [&](BusDriver& bus) {
                    at_the_registers(bus);
                    sc_core::sc_stop();
                  }} {
    if (line != nullptr) *line = &irq;
    controller.Attach(kAddress, device);
    registers.socket.bind(controller.cpu);
    controller.irq.bind(irq);
    sc_core::sc_start();
  }

  socpuppet::I2cController controller{"controller", kFiftyMegahertz};
  BusDriver registers;
  sc_core::sc_signal<bool> irq{"irq"};
};

// Switches the controller on at 100 kHz, with its interrupt if asked.
void SwitchOn(BusDriver& bus, std::uint32_t control = 0) {
  bus.Write32(I2C_CONTROLLER_PRESCALE_LOW, kPrescaleForOneHundredKilohertz);
  bus.Write32(I2C_CONTROLLER_PRESCALE_HIGH, 0);
  bus.Write32(I2C_CONTROLLER_CONTROL, I2C_CONTROLLER_CONTROL_ENABLE | control);
}

// Gives the controller a start addressed to kAddress for a write.
void GiveAStart(BusDriver& bus) {
  bus.Write32(I2C_CONTROLLER_TRANSMIT, kAddress << 1U);
  bus.Write32(I2C_CONTROLLER_COMMAND,
              I2C_CONTROLLER_COMMAND_START | I2C_CONTROLLER_COMMAND_WRITE);
}

TEST(AStartGivenToAnI2cController, ReachesTheDeviceNineOfTheBusesClocksOn) {
  TimingDevice device;
  sc_core::sc_time given_at;

  Rig rig{device, [&](BusDriver& bus) {
            SwitchOn(bus);
            GiveAStart(bus);
            given_at = sc_core::sc_time_stamp();
            bus.WaitFor(2 * AByteOnTheBus());
          }};

  EXPECT_EQ(device.started_at - given_at, AByteOnTheBus());
}

// A write that is no command takes no time on the bus, and the command
// after it takes its own from when it is given.
TEST(AStartGivenToAnI2cControllerAWhileAfterItIsSwitchedOn,
     ReachesTheDeviceNineOfTheBusesClocksAfterTheStart) {
  TimingDevice device;
  sc_core::sc_time given_at;

  Rig rig{device, [&](BusDriver& bus) {
            SwitchOn(bus);
            bus.WaitFor(AByteOnTheBus() / 2);
            GiveAStart(bus);
            given_at = sc_core::sc_time_stamp();
            bus.WaitFor(2 * AByteOnTheBus());
          }};

  EXPECT_EQ(device.started_at - given_at, AByteOnTheBus());
}

// So that a device that is a Python script may wait for the interpreter,
// as no CPU's process may: QBox's runs inside QEMU, which cannot wait.
TEST(AnI2cControllersDevice, IsCalledFromAThreadOfTheControllersOwn) {
  TimingDevice device;

  Rig rig{device, [&](BusDriver& bus) {
            SwitchOn(bus);
            GiveAStart(bus);
            bus.WaitFor(2 * AByteOnTheBus());
          }};

  EXPECT_EQ(device.caller_kind, sc_core::SC_THREAD_PROC_);
  EXPECT_TRUE(device.caller.starts_with("controller.")) << device.caller;
}

TEST(AnI2cControllersInterruptLine, RisesOnceTheCommandIsDone) {
  TimingDevice device;
  sc_core::sc_signal<bool>* line = nullptr;
  bool before = true;
  bool after = false;

  Rig rig{device,
          [&](BusDriver& bus) {
            SwitchOn(bus, I2C_CONTROLLER_CONTROL_INTERRUPT_ENABLE);
            GiveAStart(bus);
            bus.WaitFor(AByteOnTheBus() - sc_core::sc_time{1, sc_core::SC_US});
            before = line->read();
            bus.WaitFor(sc_core::sc_time{2, sc_core::SC_US});
            after = line->read();
          },
          &line};

  EXPECT_FALSE(before);
  EXPECT_TRUE(after);
}

}  // namespace
