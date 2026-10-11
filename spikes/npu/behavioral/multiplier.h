#ifndef SPIKES_NPU_BEHAVIORAL_MULTIPLIER_H_
#define SPIKES_NPU_BEHAVIORAL_MULTIPLIER_H_

#include <cstddef>
#include <cstdint>
#include <span>

namespace spike {

// The arithmetic of the behavioral NPU, apart from everything else it
// models. C = A x B: A is m by k and B is k by n, both 8-bit signed and
// row-major, and C is m by n of 32-bit signed integers, which is what a
// real NPU accumulates 8-bit products into. Returns false if the shapes
// do not fit the spans.
//
// There are two flavours. The plain one below is a triple loop in C++. The
// numpy one (numpy_multiplier.h) hands the arrays to Python.
class Multiplier {
 public:
  virtual ~Multiplier() = default;
  virtual bool Multiply(std::span<const std::int8_t> a,
                        std::span<const std::int8_t> b,
                        std::span<std::int32_t> c, std::size_t m, std::size_t k,
                        std::size_t n) = 0;

 protected:
  static bool ShapesFit(std::span<const std::int8_t> a,
                        std::span<const std::int8_t> b,
                        std::span<std::int32_t> c, std::size_t m, std::size_t k,
                        std::size_t n) {
    return a.size() == m * k && b.size() == k * n && c.size() == m * n;
  }
};

// 🎭 The arithmetic done by the machine running the simulation, with
// nothing of a processor in it: no instruction, no cycle, no clock.
class PlainMultiplier final : public Multiplier {
 public:
  bool Multiply(std::span<const std::int8_t> a, std::span<const std::int8_t> b,
                std::span<std::int32_t> c, std::size_t m, std::size_t k,
                std::size_t n) override {
    if (!ShapesFit(a, b, c, m, k, n)) return false;
    for (std::size_t row = 0; row < m; ++row) {
      for (std::size_t column = 0; column < n; ++column) {
        std::int32_t sum = 0;
        for (std::size_t inner = 0; inner < k; ++inner) {
          sum += std::int32_t{a[row * k + inner]} *
                 std::int32_t{b[inner * n + column]};
        }
        c[row * n + column] = sum;
      }
    }
    return true;
  }
};

}  // namespace spike

#endif  // SPIKES_NPU_BEHAVIORAL_MULTIPLIER_H_
