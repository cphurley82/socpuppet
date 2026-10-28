#ifndef SOCPUPPET_MODELS_I2C_CONTROLLER_H_
#define SOCPUPPET_MODELS_I2C_CONTROLLER_H_

#include <cstdint>

#include <systemc>

#include "socpuppet/core/i2c_controller_logic.h"
#include "socpuppet/core/i2c_device.h"
#include "socpuppet/models/command_device.h"

namespace socpuppet {

// A controller of an I2C bus: the OpenCores I2C master core, which is
// SiFive's I2C block, and which Zephyr's `i2c_sifive` drives. This is the
// SystemC wrapper, and the logic is in I2cControllerLogic.
//
// `cpu` is its register block and `irq` its interrupt line (see
// CommandDevice). The devices on its bus are attached by address.
class I2cController : public CommandDevice<I2cControllerLogic> {
 public:
  // `clock_hz` is the controller's clock, which the bus's is made from.
  I2cController(const sc_core::sc_module_name& name, std::uint64_t clock_hz)
      : CommandDevice(name, logic_),
        cycle_{1.0 / static_cast<double>(clock_hz), sc_core::SC_SEC} {}

  // Puts `device` on the bus at `address`, seven bits. It is not owned,
  // and must stay alive while the simulation runs.
  void Attach(std::uint8_t address, I2cDevice& device) {
    logic_.Attach(address, device);
  }

 private:
  // A command takes its time on the bus, during which the status says a
  // transfer is in progress. A write that is no command takes none.
  sc_core::sc_time TimeToCarryOut() const override {
    return cycle_ * static_cast<double>(logic_.CommandCycles());
  }

  // One cycle of the controller's clock.
  sc_core::sc_time cycle_;
  I2cControllerLogic logic_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_I2C_CONTROLLER_H_
