#ifndef SPIKES_ISS_HARNESS_VIRT_BOARD_H_
#define SPIKES_ISS_HARNESS_VIRT_BOARD_H_

#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "spikes/iss/harness/probes.h"
#include "spikes/iss/harness/standin_uart.h"

// socpuppet's built-in components include SCC's router. A candidate that
// cannot share a program with SCC is built with SPIKE_WITHOUT_SCC, and
// gets socpuppet's memory with the spike's own router instead.
#ifdef SPIKE_WITHOUT_SCC
#include "socpuppet/models/memory.h"
#include "spikes/iss/harness/simple_router.h"
#else
#include "socpuppet/models/builtin_components.h"
#endif

namespace spike {

// Where things sit on QEMU's RISC-V "virt" machine. Zephyr's qemu_riscv64
// and qemu_riscv32 boards are built for this map, so a stock Zephyr image
// for either runs here without a board of our own.
inline constexpr std::uint64_t kClintBase = 0x0200'0000;
inline constexpr std::uint64_t kClintSize = 0x1'0000;
inline constexpr std::uint64_t kPlicBase = 0x0C00'0000;
inline constexpr std::uint64_t kPlicSize = 0x40'0000;
inline constexpr std::uint64_t kUartBase = 0x1000'0000;
inline constexpr std::uint64_t kUartSize = 0x100;
inline constexpr std::uint64_t kRamBase = 0x8000'0000;
inline constexpr std::uint64_t kRamSize = 0x1000'0000;  // 256 MB

// A memory and a router, by the names and with the parameters socpuppet
// gives them.
inline socpuppet::Registry MemoryAndRouter() {
#ifdef SPIKE_WITHOUT_SCC
  socpuppet::Registry registry;
  registry.Add("memory", [](const char* name, const socpuppet::Config& config) {
    auto module = std::make_unique<socpuppet::Memory>(
        name, socpuppet::Required(config, "size", "memory"));
    std::vector<socpuppet::Port> ports{
        socpuppet::TargetPort("socket", module->socket)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  registry.Add("router", [](const char* name, const socpuppet::Config& config) {
    const std::uint64_t outputs =
        socpuppet::Required(config, "outputs", "router");
    std::vector<SimpleRouter::Range> ranges;
    for (std::uint64_t index = 0; index < outputs; ++index) {
      const std::string output = "out" + std::to_string(index);
      ranges.push_back(
          {.base = socpuppet::Required(config, output + ".base", "router"),
           .size = socpuppet::Required(config, output + ".size", "router")});
    }
    auto module = std::make_unique<SimpleRouter>(name, std::move(ranges));
    std::vector<socpuppet::Port> ports{
        socpuppet::TargetPort("target", module->target)};
    for (std::uint64_t index = 0; index < outputs; ++index) {
      ports.push_back(socpuppet::InitiatorPort("out" + std::to_string(index),
                                               module->OutputAt(index)));
    }
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  return registry;
#else
  return socpuppet::BuiltinComponents();
#endif
}

// Those, plus the spike's stand-ins.
inline socpuppet::Registry SpikeComponents() {
  socpuppet::Registry registry = MemoryAndRouter();
  registry.Add("standin_uart", [](const char* name, const socpuppet::Config&) {
    auto module = std::make_unique<StandinUart>(name);
    std::vector<socpuppet::Port> ports{
        socpuppet::TargetPort("socket", module->socket)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  // `allow_dmi` says whether direct memory access gets through it.
  registry.Add("counting_probe", [](const char* name,
                                    const socpuppet::Config& config) {
    auto module = std::make_unique<CountingProbe>(
        name, socpuppet::Required(config, "allow_dmi", "counting_probe") != 0);
    std::vector<socpuppet::Port> ports{
        socpuppet::TargetPort("target", module->target),
        socpuppet::InitiatorPort("initiator", module->initiator)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  // A wire driver. `initial` is the level it starts at.
  registry.Add(
      "line_driver", [](const char* name, const socpuppet::Config& config) {
        auto module = std::make_unique<LineDriver>(
            name, socpuppet::Required(config, "initial", "line_driver") != 0);
        std::vector<socpuppet::Port> ports{
            socpuppet::WireSourcePort("line", module->line)};
        return socpuppet::Instance{.module = std::move(module),
                                   .ports = std::move(ports)};
      });
  return registry;
}

// Whether the board's RAM grants direct memory access (DMI).
enum class Dmi { kOff, kOn };

// Builds one board in the group `board`: a CPU of the implementation named,
// a router, RAM and the stand-in UART. The interrupt controller and timer
// (PLIC and CLINT) are plain memories that soak up what is written to them.
//
// The pieces are "<board>.cpu", ".bus", ".ram", ".uart", ".clint", ".plic",
// and ".ram_probe", which counts what reaches the RAM over the bus.
inline void AddVirtBoard(socpuppet::Platform& platform,
                         const std::string& board,
                         const std::string& cpu_implementation,
                         const socpuppet::Config& cpu_config = {},
                         Dmi dmi = Dmi::kOn,
                         const std::string& uart = "standin_uart") {
  platform.Add(board + ".cpu", cpu_implementation, cpu_config);
  platform.Add(board + ".bus", "router",
               {{"outputs", 4},
                {"out0.base", kRamBase},
                {"out0.size", kRamSize},
                {"out1.base", kUartBase},
                {"out1.size", kUartSize},
                {"out2.base", kClintBase},
                {"out2.size", kClintSize},
                {"out3.base", kPlicBase},
                {"out3.size", kPlicSize}});
  platform.Add(board + ".ram", "memory", {{"size", kRamSize}});
  platform.Add(board + ".uart", uart);
  platform.Add(board + ".clint", "memory", {{"size", kClintSize}});
  platform.Add(board + ".plic", "memory", {{"size", kPlicSize}});
  platform.Add(board + ".ram_probe", "counting_probe",
               {{"allow_dmi", dmi == Dmi::kOn ? 1U : 0U}});
  platform.Bind(board + ".cpu.socket", board + ".bus.target");
  platform.Bind(board + ".bus.out0", board + ".ram_probe.target");
  platform.Bind(board + ".ram_probe.initiator", board + ".ram.socket");
  platform.Bind(board + ".bus.out1", board + ".uart.socket");
  platform.Bind(board + ".bus.out2", board + ".clint.socket");
  platform.Bind(board + ".bus.out3", board + ".plic.socket");
}

// What the board's UART has transmitted so far.
inline const std::string& UartOutput(socpuppet::Platform& platform,
                                     const std::string& board) {
  return platform.ModuleAt<StandinUart>(board + ".uart").Output();
}

// The probe in front of the board's RAM.
inline const CountingProbe& RamProbe(socpuppet::Platform& platform,
                                     const std::string& board) {
  return platform.ModuleAt<CountingProbe>(board + ".ram_probe");
}

}  // namespace spike

#endif  // SPIKES_ISS_HARNESS_VIRT_BOARD_H_
