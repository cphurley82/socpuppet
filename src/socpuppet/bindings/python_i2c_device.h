#ifndef SOCPUPPET_BINDINGS_PYTHON_I2C_DEVICE_H_
#define SOCPUPPET_BINDINGS_PYTHON_I2C_DEVICE_H_

#include <cstdint>
#include <utility>

#include <pybind11/pybind11.h>

#include "socpuppet/bindings/python_executor.h"
#include "socpuppet/core/i2c_device.h"

namespace socpuppet {

// 🧵 A device on an I2C bus that is a Python object, with the methods
// `start(read) -> bool`, `write(byte) -> bool`, `read(last) -> int` and
// `stop()`.
//
// A controller calls a device only from a thread process of its own (see
// i2c_device.h), so each call can wait for the executor, which runs Python
// on the main stack, one job at a time and in the order they were asked
// for.
class PythonI2cDevice : public I2cDevice {
 public:
  // Dropped by whoever holds this, with the GIL held.
  PythonI2cDevice(pybind11::object device, PythonExecutor& executor)
      : device_(std::move(device)), executor_(executor) {}

  bool Start(bool read) override {
    bool acknowledged = false;
    executor_.Run(
        [&] { acknowledged = device_.attr("start")(read).cast<bool>(); });
    return acknowledged;
  }

  bool Write(std::uint8_t byte) override {
    bool acknowledged = false;
    executor_.Run(
        [&] { acknowledged = device_.attr("write")(byte).cast<bool>(); });
    return acknowledged;
  }

  std::uint8_t Read(bool last) override {
    std::uint8_t byte = 0;
    executor_.Run(
        [&] { byte = device_.attr("read")(last).cast<std::uint8_t>(); });
    return byte;
  }

  void Stop() override {
    executor_.Run([this] { device_.attr("stop")(); });
  }

 private:
  pybind11::object device_;
  PythonExecutor& executor_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_BINDINGS_PYTHON_I2C_DEVICE_H_
