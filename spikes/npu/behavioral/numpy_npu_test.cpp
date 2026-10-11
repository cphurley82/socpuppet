#include <cstdint>
#include <iostream>
#include <vector>

#include <gtest/gtest.h>
#include <pybind11/embed.h>

#include "socpuppet/bindings/python_executor.h"
#include "socpuppet/platform/logging.h"
#include "spikes/npu/behavioral/host_with_an_npu.h"
#include "spikes/npu/behavioral/numpy_multiplier.h"
#include "spikes/npu/doorbell.h"

namespace spike {

namespace {

// The exit test of the spike, for the numpy flavour. The executor is a
// module of its own beside the platform, as it is in the Python
// extension, where it belongs to the module and not to any one platform.
TEST(WhenTheHostRingsTheNumpyNpuForA256By256Multiply,
     TheProductIsInMemoryAndTheLineRises) {
  constexpr std::size_t kSize = 256;
  const auto a = SomeMatrix(kSize, 1);
  const auto b = SomeMatrix(kSize, 2);
  socpuppet::PythonExecutor executor{"python_executor"};
  NumpyMultiplier multiplier{executor};
  // Importing numpy takes longer than the multiply does, and a platform
  // that used this flavour would import it once. So it is not timed.
  pybind11::module_::import("numpy");
  HostWithAnNpu bench{multiplier, RingTheBell};
  bench.PutInMemory(kAAt, a);
  bench.PutInMemory(kBAt, b);
  bench.PutInMemory(
      kDescriptorAt,
      MatmulDescriptor{
          .a = kAAt, .b = kBAt, .c = kCAt, .m = kSize, .k = kSize, .n = kSize}
          .Bytes());

  const double milliseconds = bench.RunAndTime();

  EXPECT_EQ(bench.ValuesAt<std::int32_t>(kCAt, kSize * kSize),
            Expected(a, b, kSize));
  EXPECT_EQ(bench.Rises(), 1);
  EXPECT_TRUE(bench.LineIsHigh());
  std::cout << "[  SPIKE   ] 256x256x256 int8 matmul, numpy: " << milliseconds
            << " ms of wall-clock time\n";
  RecordProperty("milliseconds", static_cast<int>(milliseconds));
}

}  // namespace

}  // namespace spike

// The interpreter lives for the whole program, as it does when socpuppet
// is an extension inside one. It is told which Python it is, so that it
// finds the virtual environment's packages (numpy) the way that Python
// would. tests/cpp/kernel_test_main.cpp, with that added.
// NOLINTNEXTLINE(bugprone-exception-escape)
int main(int argc, char** argv) {
  PyConfig config;
  PyConfig_InitPythonConfig(&config);
  PyConfig_SetBytesString(&config, &config.executable, SPIKE_PYTHON_EXECUTABLE);
  pybind11::scoped_interpreter interpreter{&config};
  ::testing::InitGoogleTest(&argc, argv);
  socpuppet::InitLogging(false);
  return RUN_ALL_TESTS();
}
