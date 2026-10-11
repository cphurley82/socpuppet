#include "spikes/npu/hexagon/integration/hexagon_npu.h"

#include <chrono>
#include <cstdint>
#include <iostream>
#include <vector>

#include <cciutils.h>
#include <gtest/gtest.h>
#include <scp/report.h>
#include <systemc>
#include <tlm>

#include "socpuppet/models/memory.h"
#include "spikes/npu/behavioral/host_with_an_npu.h"
#include "spikes/npu/doorbell.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"

namespace spike {

namespace {

// The spike's bench for the Hexagon candidate, wired by hand: socpuppet's
// Platform is not used here, because its built-in components bring SCC,
// which cannot share a program with QBox (see the ISS spike). The same
// cast as the behavioral bench's: a bus master in the host CPU's place,
// one memory of 1 MiB at address 0, and eyes on the interrupt line.
//
// The host's firmware rings the bell, waits to be interrupted, and stops
// the show: a QBox core keeps the kernel waiting, so a run with no time
// limit would never return on its own.
struct HostWithAHexagonNpu {
  explicit HostWithAHexagonNpu(const std::function<void(BusDriver&)>& body)
      : host("host", body) {
    tlm::tlm_global_quantum::instance().set(
        sc_core::sc_time(1, sc_core::SC_MS));
    host.socket.bind(npu.cpu);
    npu.socket.bind(memory.socket);
    npu.irq(irq);
    watcher.line(irq);
  }

  // bus_driver.h's DebugWrite and DebugRead take bytes as std::uint8_t.
  template <typename T>
  void PutInMemory(std::uint64_t address, const std::vector<T>& values) {
    DebugWrite(memory, address,
               std::span<const std::uint8_t>{
                   reinterpret_cast<const std::uint8_t*>(values.data()),
                   values.size() * sizeof(T)});
  }
  template <typename Bytes>
  void PutBytesInMemory(std::uint64_t address, const Bytes& bytes) {
    DebugWrite(memory, address, std::span<const std::uint8_t>{bytes});
  }
  template <typename T>
  std::vector<T> ValuesAt(std::uint64_t address, std::size_t count) {
    std::vector<T> values(count);
    DebugRead(
        memory, address,
        std::span<std::uint8_t>{reinterpret_cast<std::uint8_t*>(values.data()),
                                values.size() * sizeof(T)});
    return values;
  }

  double RunAndTime() {
    const auto started = std::chrono::steady_clock::now();
    sc_core::sc_start();
    const std::chrono::duration<double, std::milli> took =
        std::chrono::steady_clock::now() - started;
    return took.count();
  }

  socpuppet::Memory memory{"memory", HostWithAnNpu::kMemorySize};
  HexagonNpu npu{"npu", SPIKE_HEXAGON_PROGRAM};
  BusDriver host;
  LineWatcher watcher{"watcher"};
  sc_core::sc_signal<bool> irq{"irq"};
};

// The exit test of the spike, for the Hexagon candidate.
TEST(WhenTheHostRingsTheHexagonNpuForA256By256Multiply,
     TheProductIsInMemoryAndTheLineRises) {
  constexpr std::size_t kSize = 256;
  const auto a = SomeMatrix(kSize, 1);
  const auto b = SomeMatrix(kSize, 2);
  bool interrupted = false;
  HostWithAHexagonNpu bench{[&](BusDriver& host) {
    RingTheBell(host);
    interrupted =
        bench.watcher.WaitForRises(1, sc_core::sc_time(60, sc_core::SC_SEC));
    sc_core::sc_stop();
  }};
  bench.PutInMemory(kAAt, a);
  bench.PutInMemory(kBAt, b);
  bench.PutBytesInMemory(
      kDescriptorAt,
      MatmulDescriptor{
          .a = kAAt, .b = kBAt, .c = kCAt, .m = kSize, .k = kSize, .n = kSize}
          .Bytes());

  const double milliseconds = bench.RunAndTime();

  ASSERT_TRUE(interrupted);
  EXPECT_EQ(bench.ValuesAt<std::int32_t>(kCAt, kSize * kSize),
            Expected(a, b, kSize));
  std::cout << "[  SPIKE   ] 256x256x256 int8 matmul, QBox Hexagon: "
            << milliseconds << " ms of wall-clock time, "
            << sc_core::sc_time_stamp() << " simulated\n";
}

}  // namespace

}  // namespace spike

// QBox's SystemC is a shared library, and the main() inside it refers to
// sc_main() whether or not that main() is used. This satisfies the linker.
int sc_main(int, char**) { return 0; }

// A main() of our own, because QBox's parameters need their broker to exist
// before any component does (as the ISS spike's integration found).
int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  scp::init_logging(scp::LogConfig().logLevel(scp::log::WARNING));
  gs::ConfigurableBroker broker{};
  return RUN_ALL_TESTS();
}
