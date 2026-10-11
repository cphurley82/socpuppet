#ifndef SPIKES_NPU_BEHAVIORAL_HOST_WITH_AN_NPU_H_
#define SPIKES_NPU_BEHAVIORAL_HOST_WITH_AN_NPU_H_

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <span>
#include <string>
#include <utility>
#include <vector>

#include <systemc>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/npu/behavioral/behavioral_npu.h"
#include "spikes/npu/behavioral/multiplier.h"
#include "spikes/npu/doorbell.h"
#include "tests/cpp/support/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"
#include "tests/cpp/support/test_components.h"

namespace spike {

// The spike's bench for the behavioral candidate, in either flavour: a
// bus master in the host CPU's place with its hands on the NPU's
// registers, one memory of 1 MiB at address 0 that the NPU reads and
// writes, and a test's eyes on the interrupt line. `body` is what the
// host's firmware does.
struct HostWithAnNpu {
  static constexpr std::uint64_t kMemorySize = 1 << 20;

  HostWithAnNpu(Multiplier& multiplier,
                const std::function<void(BusDriver&)>& body)
      : platform{WithTheCast(multiplier, body)} {
    platform.Add("host", "bus_driver");
    platform.Add("npu", "npu");
    platform.Add("memory", "memory", {{"size", kMemorySize}});
    platform.Add("watcher", "line_watcher");
    platform.Bind("host.socket", "npu.cpu");
    platform.Bind("npu.socket", "memory.socket");
    platform.Bind("npu.irq", "watcher.line");
    platform.Elaborate();
  }

  static socpuppet::Registry WithTheCast(
      Multiplier& multiplier, const std::function<void(BusDriver&)>& body) {
    socpuppet::Registry registry = socpuppet::BuiltinComponents();
    AddBusDriver(registry, "bus_driver", body);
    AddLineWatcher(registry, "line_watcher");
    registry.Add("npu", [&multiplier](const char* name,
                                      socpuppet::Parameters&) {
      auto module = std::make_unique<BehavioralNpu>(name, multiplier);
      std::vector<socpuppet::Port> ports{
          socpuppet::TargetPort("cpu", module->cpu),
          socpuppet::InitiatorPort("socket", module->socket),
          socpuppet::WireSourcePort("irq", module->irq, /*required=*/false)};
      return socpuppet::Instance{.module = std::move(module),
                                 .ports = std::move(ports)};
    });
    return registry;
  }

  // What the memory holds, and putting bytes there, the way a debugger
  // would.
  std::vector<std::uint8_t> MemoryAt(std::uint64_t address,
                                     std::size_t length) {
    std::vector<std::uint8_t> data(length);
    platform.DebugRead("npu.socket", address,
                       std::as_writable_bytes(std::span{data}));
    return data;
  }
  // `values` is a vector or an array of anything.
  template <typename Values>
  void PutInMemory(std::uint64_t address, const Values& values) {
    const std::span<const std::byte> bytes = std::as_bytes(std::span{values});
    platform.DebugWrite("npu.socket", address, bytes);
  }
  template <typename T>
  std::vector<T> ValuesAt(std::uint64_t address, std::size_t count) {
    std::vector<T> values(count);
    platform.DebugRead("npu.socket", address,
                       std::as_writable_bytes(std::span{values}));
    return values;
  }

  // Runs the show and returns how long the machine took, in milliseconds
  // of wall-clock time. The simulation itself takes no simulated time.
  double RunAndTime() {
    const auto started = std::chrono::steady_clock::now();
    platform.Run();
    const std::chrono::duration<double, std::milli> took =
        std::chrono::steady_clock::now() - started;
    return took.count();
  }

  int Rises() { return platform.ModuleAt<LineWatcher>("watcher").Rises(); }
  bool LineIsHigh() {
    return platform.ModuleAt<LineWatcher>("watcher").line->read();
  }

  socpuppet::Platform platform;
};

// Where the bench's tests put things in memory.
inline constexpr std::uint64_t kDescriptorAt = 0x100;
inline constexpr std::uint64_t kAAt = 0x1000;
inline constexpr std::uint64_t kBAt = 0x40000;
inline constexpr std::uint64_t kCAt = 0x80000;

// What the host's firmware does: it has already put the matrices and the
// descriptor in memory, so it tells the NPU where the descriptor is, asks
// to be interrupted when the work is done, and rings the bell.
inline void RingTheBell(BusDriver& host) {
  host.Write32(kDoorbellInterruptEnable,
               kDoorbellStatusDone | kDoorbellStatusError);
  host.Write32(kDoorbellDescriptorLow,
               static_cast<std::uint32_t>(kDescriptorAt));
  host.Write32(kDoorbellDescriptorHigh,
               static_cast<std::uint32_t>(kDescriptorAt >> 32));
  host.Write32(kDoorbellCommand, kDoorbellCommandMatmul);
}

// A square matrix of `size` by `size` with something in every cell, and
// the product the test expects, computed its own way.
inline std::vector<std::int8_t> SomeMatrix(std::size_t size, std::size_t seed) {
  std::vector<std::int8_t> values(size * size);
  for (std::size_t index = 0; index < values.size(); ++index) {
    values[index] =
        static_cast<std::int8_t>((index * 7 + seed * 13) % 251 - 125);
  }
  return values;
}

inline std::vector<std::int32_t> Expected(const std::vector<std::int8_t>& a,
                                          const std::vector<std::int8_t>& b,
                                          std::size_t size) {
  std::vector<std::int32_t> c(size * size, 0);
  // Inner loop over columns, so that it is not the model's loop again.
  for (std::size_t row = 0; row < size; ++row) {
    for (std::size_t inner = 0; inner < size; ++inner) {
      const std::int32_t a_value = a[row * size + inner];
      for (std::size_t column = 0; column < size; ++column) {
        c[row * size + column] += a_value * b[inner * size + column];
      }
    }
  }
  return c;
}

}  // namespace spike

#endif  // SPIKES_NPU_BEHAVIORAL_HOST_WITH_AN_NPU_H_
