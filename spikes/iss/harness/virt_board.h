#ifndef SPIKES_ISS_HARNESS_VIRT_BOARD_H_
#define SPIKES_ISS_HARNESS_VIRT_BOARD_H_

#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "spikes/iss/harness/standin_uart.h"

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

// The built-in components, plus the spike's stand-ins.
inline socpuppet::Registry SpikeComponents() {
  socpuppet::Registry registry = socpuppet::BuiltinComponents();
  registry.Add("standin_uart", [](const char* name, const socpuppet::Config&) {
    auto module = std::make_unique<StandinUart>(name);
    std::vector<socpuppet::Port> ports{
        socpuppet::TargetPort("socket", module->socket)};
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  return registry;
}

// Builds one board in the group `board`: a CPU of the implementation named,
// a router, RAM and the stand-in UART. The interrupt controller and timer
// (PLIC and CLINT) are plain memories that soak up what is written to them.
//
// The pieces are "<board>.cpu", ".bus", ".ram", ".uart", ".clint", ".plic".
inline void AddVirtBoard(socpuppet::Platform& platform,
                         const std::string& board,
                         const std::string& cpu_implementation,
                         const socpuppet::Config& cpu_config = {}) {
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
  platform.Add(board + ".uart", "standin_uart");
  platform.Add(board + ".clint", "memory", {{"size", kClintSize}});
  platform.Add(board + ".plic", "memory", {{"size", kPlicSize}});
  platform.Bind(board + ".cpu.socket", board + ".bus.target");
  platform.Bind(board + ".bus.out0", board + ".ram.socket");
  platform.Bind(board + ".bus.out1", board + ".uart.socket");
  platform.Bind(board + ".bus.out2", board + ".clint.socket");
  platform.Bind(board + ".bus.out3", board + ".plic.socket");
}

// What the board's UART has transmitted so far.
inline const std::string& UartOutput(socpuppet::Platform& platform,
                                     const std::string& board) {
  return platform.ModuleAt<StandinUart>(board + ".uart").Output();
}

}  // namespace spike

#endif  // SPIKES_ISS_HARNESS_VIRT_BOARD_H_
