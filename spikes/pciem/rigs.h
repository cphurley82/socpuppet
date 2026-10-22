#ifndef SPIKES_PCIEM_RIGS_H_
#define SPIKES_PCIEM_RIGS_H_

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>

#include <systemc>

#include "socpuppet/core/elf_image.h"
#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "tests/cpp/support/ssd_firmware.h"

// The three drives the spike puts on the host's bus, each as an NVMe
// function with no PCIe around it: a register block, a way to the host's
// memory, and interrupt lines. pciem plays the PCIe.
namespace spike {

struct Options {
  std::string drive;
  std::uint64_t blocks = 131072;  // 64 MiB of 512-byte blocks
  unsigned vectors = 2;           // as the puppet's boards have it
  std::string board;              // zephyr: describe_ssd.py's output
  std::string elf = "build/firmware/ssd_socpuppet_ssd.elf";
  bool log = false;
  // Builds and boots the drive, and stops before it would go on the bus.
  bool dry_run = false;
  // The least CAP.TO the host is shown, in 500 ms units (host_spike.cpp).
  std::uint8_t least_timeout = 0;
};

// Where a drive's three connections are, once it is in the platform, and
// how the pump should run it.
struct Wiring {
  std::string registers;   // a bus target
  std::string dma;         // a bus source
  std::string irq_prefix;  // + the vector: a wire source
  // Zero: no CPU, so no running ahead.
  sc_core::sc_time quantum = sc_core::SC_ZERO_TIME;
  // How long, in simulated time, its firmware needs before a host may
  // enable it. Zero for a drive with none.
  sc_core::sc_time boot = sc_core::SC_ZERO_TIME;
};

// 🎭 The behavioral stand-in: one component is the whole drive.
inline Wiring AddBehavioral(socpuppet::Platform& platform,
                            const Options& options) {
  platform.Add("nvme", "behavioral_nvme",
               {{"blocks", options.blocks}, {"vectors", options.vectors}});
  return {.registers = "nvme.bar0",
          .dma = "nvme.dma",
          .irq_prefix = "nvme.irq",
          .quantum = sc_core::SC_ZERO_TIME,
          .boot = sc_core::SC_ZERO_TIME};
}

// The SSD's hardware, with the C++ firmware stand-in in its CPU's place,
// as the NVMe contract's SsdRig builds it, with a NAND the drive's size.
constexpr SsdMap kStandInMap{.frontend = 0x1001'0000,
                             .dma = 0x1002'0000,
                             .flash = 0x1003'0000,
                             .buffer = 0x4000'0000};

inline void RegisterStandIn(socpuppet::Registry& registry) {
  AddSsdFirmware(registry, "ssd_firmware", kStandInMap);
}

inline Wiring AddStandIn(socpuppet::Platform& platform,
                         const Options& options) {
  constexpr std::uint64_t kPageSize = 4096;
  constexpr std::uint64_t kPagesPerBlock = 64;
  constexpr std::uint64_t kBufferSize = 0x1'0000;
  const std::uint64_t pages = options.blocks * 512 / kPageSize;
  platform.Add("ssd.cpu", "ssd_firmware");
  platform.Add("ssd.bus", "router",
               {{"inputs", 3},
                {"outputs", 4},
                {"out0.base", kStandInMap.frontend},
                {"out0.size", 0x80},
                {"out1.base", kStandInMap.dma},
                {"out1.size", 0x20},
                {"out2.base", kStandInMap.flash},
                {"out2.size", 0x30},
                {"out3.base", kStandInMap.buffer},
                {"out3.size", kBufferSize}});
  platform.Add("ssd.frontend", "nvme_frontend", {{"vectors", options.vectors}});
  platform.Add("ssd.dma", "dma_engine");
  platform.Add("ssd.flash", "flash_controller");
  platform.Add("ssd.nand", "ideal_nand",
               {{"blocks", pages / kPagesPerBlock},
                {"pages_per_block", kPagesPerBlock},
                {"page_size", kPageSize}});
  platform.Add("ssd.buffer", "memory", {{"size", kBufferSize}});
  platform.Add("ssd.uplink", "router",
               {{"inputs", 2},
                {"outputs", 1},
                {"out0.base", 0},
                {"out0.size", std::uint64_t{1} << 63}});
  platform.Bind("ssd.cpu.socket", "ssd.bus.target");
  platform.Bind("ssd.bus.out0", "ssd.frontend.cpu");
  platform.Bind("ssd.bus.out1", "ssd.dma.cpu");
  platform.Bind("ssd.bus.out2", "ssd.flash.cpu");
  platform.Bind("ssd.bus.out3", "ssd.buffer.socket");
  platform.Bind("ssd.frontend.cpu_irq", "ssd.cpu.irq");
  platform.Bind("ssd.dma.local", "ssd.bus.in1");
  platform.Bind("ssd.flash.local", "ssd.bus.in2");
  platform.Bind("ssd.flash.nand", "ssd.nand.socket");
  platform.Bind("ssd.frontend.dma", "ssd.uplink.target");
  platform.Bind("ssd.dma.host", "ssd.uplink.in1");
  return {.registers = "ssd.frontend.bar0",
          .dma = "ssd.uplink.out0",
          .irq_prefix = "ssd.frontend.irq",
          .quantum = sc_core::SC_ZERO_TIME,
          .boot = sc_core::SC_ZERO_TIME};
}

// The SSD with its own CPU, as Python's add_ssd_function describes it
// (describe_ssd.py), running Zephyr's SSD firmware.
inline Wiring AddZephyr(socpuppet::Platform& platform, const Options& options) {
  std::ifstream board(options.board);
  if (!board) {
    throw std::invalid_argument(
        "zephyr needs --board <file>, from spikes/pciem/describe_ssd.py, "
        "and \"" +
        options.board + "\" cannot be read");
  }
  Wiring wiring{.registers = "frontend.bar0",
                .dma = "uplink.out0",
                .irq_prefix = "frontend.irq",
                .quantum = sc_core::SC_ZERO_TIME,  // the board's, below
                // Long enough for the FTL to look for a saved table and
                // say it is ready: about 4 ms for 2 MiB, 0.27 s for 2 GiB.
                .boot = sc_core::sc_time(50, sc_core::SC_MS)};
  std::string line;
  while (std::getline(board, line)) {
    std::istringstream words(line);
    std::string verb;
    words >> verb;
    if (verb == "quantum") {
      std::uint64_t picoseconds = 0;
      words >> picoseconds;
      wiring.quantum =
          sc_core::sc_time(static_cast<double>(picoseconds), sc_core::SC_PS);
    } else if (verb == "add") {
      std::string path;
      std::string implementation;
      words >> path >> implementation;
      socpuppet::Config config;
      std::string parameter;
      while (words >> parameter) {
        const std::size_t equals = parameter.find('=');
        config[parameter.substr(0, equals)] =
            std::stoull(parameter.substr(equals + 1));
      }
      if (implementation == "nvme_frontend")
        config["vectors"] = options.vectors;
      // The uplink, mapped onto the bridge from address 0 up.
      if (path == "uplink") {
        config["outputs"] = 1;
        config["out0.base"] = 0;
        config["out0.size"] = std::uint64_t{1} << 63;
      }
      platform.Add(path, implementation, config);
    } else if (verb == "connect") {
      std::string source;
      std::string sink;
      words >> source >> sink;
      platform.Bind(source, sink);
    }
  }
  return wiring;
}

// Puts the firmware into the SSD's SRAM, through its CPU, as Python's
// Platform.load_elf does.
inline void LoadFirmware(socpuppet::Platform& platform,
                         const Options& options) {
  const socpuppet::ElfImage image = socpuppet::ReadElfImage(options.elf);
  for (const socpuppet::ElfImage::Segment& segment : image.segments) {
    if (!platform.DebugWrite("cpu.socket", segment.address, segment.bytes)) {
      throw std::invalid_argument("nothing at the address " +
                                  std::to_string(segment.address) + " of " +
                                  options.elf + " took its bytes");
    }
  }
}

}  // namespace spike

#endif  // SPIKES_PCIEM_RIGS_H_
