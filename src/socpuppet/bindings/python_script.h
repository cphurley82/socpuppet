#pragma once

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>

#include <pybind11/pybind11.h>

#include "socpuppet/bindings/python_executor.h"
#include "socpuppet/core/script.h"

namespace socpuppet {

// A Python generator function, played as a bus master's script.
//
// Every touch of a Python object happens inside a job on the PythonExecutor,
// on the main stack with the GIL held. That includes dropping references:
// this object is owned by the Python-side platform and is destroyed from
// Python, never from a SystemC thread.
class PythonScript {
 public:
  PythonScript(pybind11::object generator_function, PythonExecutor& executor)
      : generator_function_(std::move(generator_function)),
        to_native_(pybind11::module_::import("socpuppet.ops").attr("to_native")),
        executor_(executor) {}

  // Starts the Python script from the top and plays it to the end. Stops
  // early if Python raises; the exception then comes out of run().
  Script play() {
    if (!executor_.run([this] { generator_ = generator_function_(); })) co_return;
    std::optional<std::uint32_t> read_value;
    while (std::optional<Op> op = next(read_value)) {
      const std::uint32_t given_back = co_await *op;
      read_value = std::holds_alternative<Read32>(*op) ? std::optional{given_back} : std::nullopt;
    }
  }

 private:
  // Advances the generator, sending it the last read's value if there was
  // one, and returns the op it yields. Returns nothing when the script has
  // finished or has failed.
  std::optional<Op> next(std::optional<std::uint32_t> read_value) {
    std::optional<Op> op;
    executor_.run([&] {
      namespace py = pybind11;
      try {
        py::object yielded = read_value ? generator_.attr("send")(*read_value)
                                        : generator_.attr("send")(py::none());
        op = to_op(to_native_(yielded));
      } catch (py::error_already_set& error) {
        if (!error.matches(PyExc_StopIteration)) throw;
      }
    });
    return op;
  }

  static Op to_op(const pybind11::tuple& native) {
    const auto kind = native[0].cast<std::string>();
    const auto number = [&](std::size_t index) { return native[index].cast<std::uint64_t>(); };
    if (kind == "read32") return Read32{number(1)};
    if (kind == "write32") return Write32{number(1), static_cast<std::uint32_t>(number(2))};
    if (kind == "expect32") return Expect32{number(1), static_cast<std::uint32_t>(number(2))};
    if (kind == "wait") return Wait{Picoseconds{number(1)}};
    if (kind == "wait_irq") return WaitIrq{};
    throw std::invalid_argument("socpuppet.ops produced an operation of unknown kind \"" +
                                kind + "\".");
  }

  pybind11::object generator_function_;
  pybind11::object to_native_;
  pybind11::object generator_;
  PythonExecutor& executor_;
};

}  // namespace socpuppet
