#ifndef SOCPUPPET_BINDINGS_PYTHON_SPI_DEVICE_H_
#define SOCPUPPET_BINDINGS_PYTHON_SPI_DEVICE_H_

#include <cstdint>
#include <utility>

#include <pybind11/pybind11.h>

#include "socpuppet/bindings/python_executor.h"
#include "socpuppet/core/spi_device.h"

namespace socpuppet {

// 🧵 A device on an SPI bus that is a Python object, with the methods
// `select()`, `transfer(byte) -> int` and `deselect()`.
//
// A controller calls a device only from thread processes of its own (see
// spi_device.h), so each call can wait for the executor, which runs Python
// on the main stack, one job at a time and in the order they were asked
// for.
class PythonSpiDevice : public SpiDevice {
 public:
  // Dropped by whoever holds this, with the GIL held.
  PythonSpiDevice(pybind11::object device, PythonExecutor& executor)
      : device_(std::move(device)), executor_(executor) {}

  void Select() override {
    executor_.Run([this] { device_.attr("select")(); });
  }

  std::uint8_t Transfer(std::uint8_t sent) override {
    std::uint8_t answer = 0;
    executor_.Run(
        [&] { answer = device_.attr("transfer")(sent).cast<std::uint8_t>(); });
    return answer;
  }

  void Deselect() override {
    executor_.Run([this] { device_.attr("deselect")(); });
  }

 private:
  pybind11::object device_;
  PythonExecutor& executor_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_BINDINGS_PYTHON_SPI_DEVICE_H_
