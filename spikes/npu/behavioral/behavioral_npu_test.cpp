#include <cstdint>
#include <iostream>
#include <vector>

#include <gtest/gtest.h>

#include "spikes/npu/behavioral/host_with_an_npu.h"
#include "spikes/npu/behavioral/multiplier.h"
#include "spikes/npu/doorbell.h"

namespace spike {

namespace {

// The exit test of the spike, for the C++ flavour: one matrix multiply
// from a descriptor in memory, the product written back, and the host's
// interrupt raised.
TEST(WhenTheHostRingsTheBehavioralNpuForA256By256Multiply,
     TheProductIsInMemoryAndTheLineRises) {
  constexpr std::size_t kSize = 256;
  const auto a = SomeMatrix(kSize, 1);
  const auto b = SomeMatrix(kSize, 2);
  PlainMultiplier multiplier;
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
  std::cout << "[  SPIKE   ] 256x256x256 int8 matmul, plain C++: "
            << milliseconds << " ms of wall-clock time\n";
  RecordProperty("milliseconds", static_cast<int>(milliseconds));
}

// A small one that a reader can check by hand.
TEST(WhenTheHostRingsTheBehavioralNpuForA2By3Times3By2Multiply,
     TheProductIsWhatArithmeticSays) {
  PlainMultiplier multiplier;
  HostWithAnNpu bench{multiplier, RingTheBell};
  bench.PutInMemory(kAAt, std::vector<std::int8_t>{1, 2, 3, 4, 5, 6});
  bench.PutInMemory(kBAt, std::vector<std::int8_t>{7, 8, 9, 10, 11, 12});
  bench.PutInMemory(
      kDescriptorAt,
      MatmulDescriptor{.a = kAAt, .b = kBAt, .c = kCAt, .m = 2, .k = 3, .n = 2}
          .Bytes());

  bench.platform.Run();

  EXPECT_EQ(bench.ValuesAt<std::int32_t>(kCAt, 4),
            (std::vector<std::int32_t>{58, 64, 139, 154}));
}

TEST(WhenTheDescriptorIsSomewhereTheNpuCannotRead,
     TheStatusSaysErrorAndTheLineRises) {
  std::uint32_t status = 0;
  PlainMultiplier multiplier;
  HostWithAnNpu bench{multiplier, [&](BusDriver& host) {
                        host.Write32(kDoorbellInterruptEnable,
                                     kDoorbellStatusError);
                        host.Write32(kDoorbellDescriptorLow, 0);
                        host.Write32(kDoorbellDescriptorHigh, 0x10);  // 64 GiB
                        host.Write32(kDoorbellCommand, kDoorbellCommandMatmul);
                        host.WaitFor(sc_core::SC_ZERO_TIME);
                        host.WaitFor(sc_core::SC_ZERO_TIME);
                        status = host.Read32(kDoorbellStatus);
                      }};

  bench.platform.Run();

  EXPECT_EQ(status, kDoorbellStatusError);
  EXPECT_EQ(bench.Rises(), 1);
}

TEST(WhenTheHostClearsDoneAfterTheNpuInterruptedIt, TheLineFalls) {
  PlainMultiplier multiplier;
  HostWithAnNpu bench{
      multiplier, [&](BusDriver& host) {
        RingTheBell(host);
        while ((host.Read32(kDoorbellStatus) & kDoorbellStatusBusy) != 0) {
          host.WaitFor(sc_core::SC_ZERO_TIME);
        }
        host.Write32(kDoorbellStatus, kDoorbellStatusDone);
      }};
  bench.PutInMemory(kAAt, std::vector<std::int8_t>{1});
  bench.PutInMemory(kBAt, std::vector<std::int8_t>{1});
  bench.PutInMemory(
      kDescriptorAt,
      MatmulDescriptor{.a = kAAt, .b = kBAt, .c = kCAt, .m = 1, .k = 1, .n = 1}
          .Bytes());

  bench.platform.Run();

  EXPECT_EQ(bench.Rises(), 1);
  EXPECT_FALSE(bench.LineIsHigh());
}

}  // namespace

}  // namespace spike
