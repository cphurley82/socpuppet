#include <cstdint>
#include <string>

#include <gtest/gtest.h>

#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/contracts/nvme_contract.h"
#include "tests/cpp/support/ssd_firmware.h"

namespace {

// The behavioral stand-in: one built-in component is the whole function.
struct BehavioralNvmeRig {
  static constexpr std::uint64_t kBlocks = 64;
  static constexpr unsigned kVectors = 2;

  static void Register(socpuppet::Registry&) {}
  static void Add(socpuppet::Platform& platform) {
    platform.Add("nvme", "behavioral_nvme",
                 {{"blocks", kBlocks}, {"vectors", kVectors}});
  }
  static const char* Registers() { return "nvme.bar0"; }
  static const char* Dma() { return "nvme.dma"; }
  static std::string Irq(unsigned vector) {
    return "nvme.irq" + std::to_string(vector);
  }
};

// The SSD: its hardware, with a stand-in for the firmware in its CPU's
// place.
//
// clang-format off
//   the host ══ frontend ◀─ registers ─ firmware ─ registers ─▶ dma, flash
//                  │                                             │      │
//                  └──────────▶ uplink ◀─────────────────────────┘      ▼
//                                 │        dma, flash ─▶ bus ─▶ buffer  nand
//                                 ▼
//                          the host's memory
// clang-format on
//
// The frontend fetches commands and posts completions, the DMA engine
// moves a command's data, and both reach the host's memory through one
// way up, the uplink. Behind it the firmware has a bus of its own, with
// the three devices' registers and a buffer on it.
struct SsdRig {
  // The NAND is one block of 8 pages of 4 KiB, which is 64 of the drive's
  // 512-byte blocks.
  static constexpr std::uint64_t kNandPages = 8;
  static constexpr std::uint64_t kNandPageSize = 4096;
  static constexpr std::uint64_t kBlocks = kNandPages * kNandPageSize / 512;
  static constexpr unsigned kVectors = 2;

  // The SSD's own address map, which only the firmware and the two devices
  // that move data see.
  static constexpr SsdMap kMap{.frontend = 0x1001'0000,
                               .dma = 0x1002'0000,
                               .flash = 0x1003'0000,
                               .buffer = 0x4000'0000};
  static constexpr std::uint64_t kBufferSize = 0x1'0000;
  // The uplink passes an address on unchanged. It does so for the lower
  // half of all the addresses 64 bits can say, which is far more than any
  // host here has.
  static constexpr std::uint64_t kAddressesTheUplinkPassesOn = std::uint64_t{1}
                                                               << 63;

  static void Register(socpuppet::Registry& registry) {
    AddSsdFirmware(registry, "ssd_firmware", kMap);
  }

  static void Add(socpuppet::Platform& platform) {
    platform.Add("ssd.cpu", "ssd_firmware");
    platform.Add("ssd.bus", "router",
                 {{"inputs", 3},
                  {"outputs", 4},
                  {"out0.base", kMap.frontend},
                  {"out0.size", 0x80},
                  {"out1.base", kMap.dma},
                  {"out1.size", 0x20},
                  {"out2.base", kMap.flash},
                  {"out2.size", 0x30},
                  {"out3.base", kMap.buffer},
                  {"out3.size", kBufferSize}});
    platform.Add("ssd.frontend", "nvme_frontend", {{"vectors", kVectors}});
    platform.Add("ssd.dma", "dma_engine");
    platform.Add("ssd.flash", "flash_controller");
    platform.Add("ssd.nand", "ideal_nand",
                 {{"blocks", 1},
                  {"pages_per_block", kNandPages},
                  {"page_size", kNandPageSize}});
    platform.Add("ssd.buffer", "memory", {{"size", kBufferSize}});
    platform.Add("ssd.uplink", "router",
                 {{"inputs", 2},
                  {"outputs", 1},
                  {"out0.base", 0},
                  {"out0.size", kAddressesTheUplinkPassesOn}});
    // The firmware's bus.
    platform.Bind("ssd.cpu.socket", "ssd.bus.target");
    platform.Bind("ssd.bus.out0", "ssd.frontend.cpu");
    platform.Bind("ssd.bus.out1", "ssd.dma.cpu");
    platform.Bind("ssd.bus.out2", "ssd.flash.cpu");
    platform.Bind("ssd.bus.out3", "ssd.buffer.socket");
    platform.Bind("ssd.frontend.cpu_irq", "ssd.cpu.irq");
    // The two devices that move data reach the buffer over the same bus.
    platform.Bind("ssd.dma.local", "ssd.bus.in1");
    platform.Bind("ssd.flash.local", "ssd.bus.in2");
    platform.Bind("ssd.flash.nand", "ssd.nand.socket");
    // The way up to the host's memory.
    platform.Bind("ssd.frontend.dma", "ssd.uplink.target");
    platform.Bind("ssd.dma.host", "ssd.uplink.in1");
  }
  static const char* Registers() { return "ssd.frontend.bar0"; }
  static const char* Dma() { return "ssd.uplink.out0"; }
  static std::string Irq(unsigned vector) {
    return "ssd.frontend.irq" + std::to_string(vector);
  }
};

}  // namespace

INSTANTIATE_TYPED_TEST_SUITE_P(Behavioral, NvmeContract,
                               ::testing::Types<BehavioralNvmeRig>);
INSTANTIATE_TYPED_TEST_SUITE_P(Ssd, NvmeContract, ::testing::Types<SsdRig>);
