#ifndef SPIKES_PCIE_RIG_H_
#define SPIKES_PCIE_RIG_H_

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <span>
#include <string>
#include <utility>
#include <vector>

#include <gtest/gtest.h>
#include <systemc>
#include <tlm>

#include "socpuppet/platform/platform.h"
#include "socpuppet/platform/registry.h"
#include "spikes/pcie/components.h"
#include "spikes/pcie/test_support.h"
#include "tests/cpp/contracts/bus_driver.h"
#include "tests/cpp/support/line_watcher.h"

namespace spike {

// The host's address map.
constexpr std::uint64_t kMsiBase = 0x2400'0000;  // where MSI-X messages go
constexpr std::uint64_t kMsiSize = 0x1000;
constexpr std::uint64_t kEcamBase = 0x3000'0000;  // configuration space
constexpr std::uint64_t kEcamSize = 0x1000'0000;  // 256 buses
constexpr std::uint64_t kMmioBase = 0x4000'0000;  // the window BARs go in
constexpr std::uint64_t kMmioSize = 0x1000'0000;
constexpr std::uint64_t kMemoryBase = 0x8000'0000;
constexpr std::uint64_t kMemorySize = 0x10'0000;

// Configuration space: the registers every PCI function has.
constexpr unsigned kIds = 0x00;
constexpr unsigned kCommand = 0x04;
constexpr std::uint16_t kMemoryEnable = 1U << 1;
constexpr std::uint16_t kBusMasterEnable = 1U << 2;
constexpr unsigned kStatus = 0x06;
constexpr std::uint16_t kHasCapabilities = 1U << 4;
constexpr unsigned kClassAndRevision = 0x08;
constexpr unsigned kBar0 = 0x10;
constexpr unsigned kBar1 = 0x14;
constexpr unsigned kCapabilitiesPointer = 0x34;
constexpr std::uint8_t kMsixCapability = 0x11;
// Inside the MSI-X capability.
constexpr unsigned kMessageControl = 2;
constexpr std::uint16_t kMsixEnable = 1U << 15;
constexpr std::uint16_t kFunctionMask = 1U << 14;
constexpr unsigned kTableOffset = 4;
constexpr unsigned kPendingOffset = 8;

// Every component a test platform is made from: socpuppet's own, the
// endpoint, and the test's stand-ins and spies.
inline socpuppet::Registry SpikeComponents() {
  using socpuppet::Config;
  using socpuppet::Instance;
  using socpuppet::Port;
  socpuppet::Registry registry = WithVcmlEndpoint();
  registry.Add("function_stand_in", [](const char* name, const Config&) {
    auto module = std::make_unique<FunctionStandIn>(name, kVectors);
    std::vector<Port> ports{socpuppet::TargetPort("bar0", module->bar0),
                            socpuppet::InitiatorPort("dma", module->dma)};
    for (std::size_t vector = 0; vector < kVectors; ++vector) {
      ports.push_back(socpuppet::WireSourcePort("irq" + std::to_string(vector),
                                                module->irq[vector]));
    }
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("bus_spy", [](const char* name, const Config&) {
    auto module = std::make_unique<BusSpy>(name);
    std::vector<Port> ports{
        socpuppet::TargetPort("target", module->target),
        socpuppet::InitiatorPort("initiator", module->initiator)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("msi_catcher", [](const char* name, const Config&) {
    auto module = std::make_unique<MsiCatcher>(name, kVectors);
    std::vector<Port> ports{socpuppet::TargetPort("socket", module->socket)};
    for (std::size_t vector = 0; vector < kVectors; ++vector) {
      ports.push_back(socpuppet::WireSourcePort("line" + std::to_string(vector),
                                                module->line[vector],
                                                /*required=*/false));
    }
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("line_watcher", [](const char* name, const Config&) {
    auto module = std::make_unique<LineWatcher>(name);
    std::vector<Port> ports{socpuppet::WireSinkPort("line", module->line)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  return registry;
}

// What the host's software does to a PCIe function, in a BusDriver's
// thread: configuration accesses through the ECAM window, and the steps
// of enumeration.
class PciHost {
 public:
  explicit PciHost(BusDriver& bus) : bus_(bus) {}

  // The address of a configuration register in the ECAM window: 4 KiB of
  // configuration space for each bus, device and function.
  static std::uint64_t Ecam(unsigned bus, unsigned device, unsigned function,
                            unsigned reg) {
    return kEcamBase +
           (std::uint64_t{bus} << 20 | device << 15 | function << 12 | reg);
  }

  template <typename Value = std::uint32_t>
  Value Read(std::uint64_t address) {
    Value value{};
    last_status_ = bus_.Read(
        address,
        std::span{reinterpret_cast<std::uint8_t*>(&value), sizeof value});
    return value;
  }
  template <typename Value = std::uint32_t>
  void Write(std::uint64_t address, Value value) {
    last_status_ = bus_.Write(
        address,
        std::span{reinterpret_cast<const std::uint8_t*>(&value), sizeof value});
  }
  // How the last Read or Write was answered.
  tlm::tlm_response_status LastStatus() const { return last_status_; }

  // Function 00:00.0, where the endpoint is.
  template <typename Value = std::uint32_t>
  Value Config(unsigned reg) {
    return Read<Value>(Ecam(0, 0, 0, reg));
  }
  template <typename Value = std::uint32_t>
  void SetConfig(unsigned reg, Value value) {
    Write<Value>(Ecam(0, 0, 0, reg), value);
  }

  // Sizes BAR0 the way Zephyr's pcie.c does: decoding off, all ones in,
  // the size mask out. Returns the size, and leaves the BAR as it found it.
  std::uint64_t SizeOfBar0() {
    const auto low = Config(kBar0);
    const auto high = Config(kBar1);
    const auto command = Config<std::uint16_t>(kCommand);
    SetConfig<std::uint16_t>(kCommand, command & ~kMemoryEnable);
    SetConfig(kBar0, 0xFFFF'FFFFU);
    std::uint64_t mask = Config(kBar0);
    SetConfig(kBar0, low);
    SetConfig(kBar1, 0xFFFF'FFFFU);
    mask |= std::uint64_t{Config(kBar1)} << 32;
    SetConfig(kBar1, high);
    SetConfig<std::uint16_t>(kCommand, command);
    mask &= ~std::uint64_t{0xF};  // the low four bits say what kind of BAR
    return mask & ~(mask - 1);
  }

  // Gives BAR0 a PCI bus address, and returns where the host's bus has it:
  // the root complex's window starts at kMmioBase.
  std::uint64_t PlaceBar0(std::uint64_t bus_address) {
    SetConfig(kBar0, static_cast<std::uint32_t>(bus_address));
    SetConfig(kBar1, static_cast<std::uint32_t>(bus_address >> 32));
    return kMmioBase + bus_address;
  }

  // Follows the capability list to the capability with this identifier.
  // Returns where in configuration space it is, or 0 if it is not there.
  unsigned FindCapability(std::uint8_t wanted) {
    if ((Config<std::uint16_t>(kStatus) & kHasCapabilities) == 0) return 0;
    unsigned at = Config<std::uint8_t>(kCapabilitiesPointer);
    for (int hops = 0; at != 0 && hops < 48; ++hops) {
      if (Config<std::uint8_t>(at) == wanted) return at;
      at = Config<std::uint8_t>(at + 1);
    }
    return 0;
  }

  // The whole of enumeration: places BAR0, switches on memory decoding and
  // bus mastering, points every MSI-X vector N at kMsiBase with N as its
  // data, unmasked, and enables MSI-X. Returns where BAR0 is on the bus.
  std::uint64_t BringUp(std::uint64_t bus_address = 0x10'0000) {
    const std::uint64_t bar0 = PlaceBar0(bus_address);
    SetConfig<std::uint16_t>(kCommand, kMemoryEnable | kBusMasterEnable);
    const unsigned msix = FindCapability(kMsixCapability);
    const std::uint64_t table = bar0 + (Config(msix + kTableOffset) & ~7U);
    const auto control = Config<std::uint16_t>(msix + kMessageControl);
    for (std::uint32_t vector = 0; vector <= (control & 0x7FFU); ++vector) {
      SetVector(table, vector, kMsiBase, vector, /*masked=*/false);
    }
    SetConfig<std::uint16_t>(msix + kMessageControl, control | kMsixEnable);
    return bar0;
  }

  // One entry of the MSI-X table: 16 bytes, written as four 32-bit words.
  void SetVector(std::uint64_t table, std::uint32_t vector,
                 std::uint64_t address, std::uint32_t data, bool masked) {
    const std::uint64_t entry = table + (16 * vector);
    Write(entry, static_cast<std::uint32_t>(address));
    Write(entry + 4, static_cast<std::uint32_t>(address >> 32));
    Write(entry + 8, data);
    Write(entry + 12, std::uint32_t{masked ? 1U : 0U});
  }

  void Wait(const sc_core::sc_time& duration = {1, sc_core::SC_US}) {
    bus_.WaitFor(duration);
  }

  BusDriver& Bus() { return bus_; }

 private:
  BusDriver& bus_;
  tlm::tlm_response_status last_status_ = tlm::TLM_INCOMPLETE_RESPONSE;
};

// The host around the endpoint, the same for every test:
//
//   host.driver ─▶ host.bus ─┬─▶ host.memory
//                     ▲      ├─▶ host.msi         (catches MSI-X messages)
//                     │      ├─▶ pcie.ecam
//                     │      └─▶ pcie.mmio
//                     └── host.dma_spy ◀── pcie.dma
//
// A test adds the function behind the endpoint, binds it to the ports
// pcie.bar0, pcie.function_dma and pcie.irqN, and then calls OnTheHost().
class Rig {
 public:
  explicit Rig(const socpuppet::Config& endpoint = {})
      : platform_(std::make_unique<socpuppet::Platform>(Components())) {
    platform_->Add("host.driver", "driver");
    platform_->Add("host.bus", "router",
                   {{"inputs", 2},
                    {"outputs", 4},
                    {"out0.base", kMemoryBase},
                    {"out0.size", kMemorySize},
                    {"out1.base", kMsiBase},
                    {"out1.size", kMsiSize},
                    {"out2.base", kEcamBase},
                    {"out2.size", kEcamSize},
                    {"out3.base", kMmioBase},
                    {"out3.size", kMmioSize}});
    platform_->Add("host.memory", "memory", {{"size", kMemorySize}});
    platform_->Add("host.msi", "msi_catcher");
    platform_->Add("host.dma_spy", "bus_spy");
    platform_->Add("pcie", "vcml_pcie_endpoint", endpoint);
    platform_->Bind("host.driver.socket", "host.bus.target");
    platform_->Bind("host.bus.out0", "host.memory.socket");
    platform_->Bind("host.bus.out1", "host.msi.socket");
    platform_->Bind("host.bus.out2", "pcie.ecam");
    platform_->Bind("host.bus.out3", "pcie.mmio");
    platform_->Bind("pcie.dma", "host.dma_spy.target");
    platform_->Bind("host.dma_spy.initiator", "host.bus.in1");
  }

  socpuppet::Platform& Platform() { return *platform_; }
  BusSpy& DmaSpy() { return platform_->ModuleAt<BusSpy>("host.dma_spy"); }
  MsiCatcher& Msi() { return platform_->ModuleAt<MsiCatcher>("host.msi"); }

  // Elaborates the platform and runs it with `body` as what the host's
  // software does. The run ends when the body returns.
  void OnTheHost(std::function<void(BusDriver&)> body) {
    body_ = std::move(body);
    platform_->Elaborate();
    platform_->Run();
  }

  // The same, but nothing ends the run when the body returns: it ends only
  // if the kernel finds nothing left to do.
  void OnTheHostUntilNothingIsLeft(std::function<void(BusDriver&)> body) {
    pause_after_body_ = false;
    OnTheHost(std::move(body));
  }

 private:
  socpuppet::Registry Components() {
    socpuppet::Registry registry = SpikeComponents();
    registry.Add("driver", [this](const char* name, const socpuppet::Config&) {
      auto module = std::make_unique<BusDriver>(name, [this](BusDriver& bus) {
        body_(bus);
        if (pause_after_body_) sc_core::sc_pause();
      });
      std::vector<socpuppet::Port> ports{
          socpuppet::InitiatorPort("socket", module->socket)};
      return socpuppet::Instance{.module = std::move(module),
                                 .ports = std::move(ports)};
    });
    return registry;
  }

  std::function<void(BusDriver&)> body_;
  bool pause_after_body_ = true;
  std::unique_ptr<socpuppet::Platform> platform_;
};

// The rig with the stand-in function behind the endpoint.
class StandInRig : public Rig {
 public:
  explicit StandInRig(const socpuppet::Config& endpoint = {}) : Rig(endpoint) {
    Platform().Add("function", "function_stand_in");
    Platform().Bind("pcie.bar0", "function.bar0");
    Platform().Bind("function.dma", "pcie.function_dma");
    for (std::size_t vector = 0; vector < kVectors; ++vector) {
      const std::string irq = "irq" + std::to_string(vector);
      Platform().Bind("function." + irq, "pcie." + irq);
    }
  }

  FunctionStandIn& Function() {
    return Platform().ModuleAt<FunctionStandIn>("function");
  }
};

}  // namespace spike

#endif  // SPIKES_PCIE_RIG_H_
