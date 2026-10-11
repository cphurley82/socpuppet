#ifndef SPIKES_NPU_BEHAVIORAL_NUMPY_MULTIPLIER_H_
#define SPIKES_NPU_BEHAVIORAL_NUMPY_MULTIPLIER_H_

#include <cstddef>
#include <cstdint>
#include <span>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include "socpuppet/bindings/python_executor.h"
#include "spikes/npu/behavioral/multiplier.h"

namespace spike {

// 🧵 The arithmetic handed to numpy: Python pulling the strings quite
// literally. The multiply runs on the main stack through socpuppet's
// PythonExecutor, because it is called from a SystemC thread process and
// CPython may not be called from one of those (see python_executor.h).
// The arrays are copied in and out: 64 KiB each way for the spike's
// 256 by 256 case, which is nothing beside the multiply.
class NumpyMultiplier final : public Multiplier {
 public:
  explicit NumpyMultiplier(socpuppet::PythonExecutor& executor)
      : executor_(executor) {}

  bool Multiply(std::span<const std::int8_t> a, std::span<const std::int8_t> b,
                std::span<std::int32_t> c, std::size_t m, std::size_t k,
                std::size_t n) override {
    if (!ShapesFit(a, b, c, m, k, n)) return false;
    return executor_.Run([&] {
      namespace py = pybind11;
      const auto rows = static_cast<py::ssize_t>(m);
      const auto inner = static_cast<py::ssize_t>(k);
      const auto columns = static_cast<py::ssize_t>(n);
      py::array_t<std::int8_t> a_array({rows, inner}, a.data());
      py::array_t<std::int8_t> b_array({inner, columns}, b.data());
      // numpy's matmul of two int8 arrays accumulates in int8 and wraps, so
      // the operands are widened first, which is what the hardware does.
      const py::object int32 = py::module_::import("numpy").attr("int32");
      const py::object product = a_array.attr("astype")(int32).attr(
          "__matmul__")(b_array.attr("astype")(int32));
      const auto c_array =
          py::array_t<std::int32_t, py::array::c_style |
                                        py::array::forcecast>::ensure(product);
      std::copy_n(c_array.data(), c.size(), c.begin());
    });
  }

 private:
  socpuppet::PythonExecutor& executor_;
};

}  // namespace spike

#endif  // SPIKES_NPU_BEHAVIORAL_NUMPY_MULTIPLIER_H_
