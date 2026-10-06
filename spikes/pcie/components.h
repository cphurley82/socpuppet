#ifndef SPIKES_PCIE_COMPONENTS_H_
#define SPIKES_PCIE_COMPONENTS_H_

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "socpuppet/models/builtin_components.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "spikes/pcie/vcml_bare_endpoint.h"
#include "spikes/pcie/vcml_endpoint.h"

namespace spike {

// What the endpoint is told to be unless its parameters say otherwise: an
// NVMe controller (class code 01/08/02) from a made-up maker, with the
// behavioral NVMe function's 0x2000 bytes of registers behind BAR0.
constexpr std::uint16_t kVendorId = 0x1DE5;
constexpr std::uint16_t kDeviceId = 0x50C0;
constexpr std::uint32_t kNvmeClassCode = 0x010802;
constexpr std::uint64_t kFunctionSize = 0x2000;
constexpr std::size_t kVectors = 4;

// Which of the spike's two adapters "vcml_pcie_endpoint" is: the one with
// VCML's PCI host inside, or, when built with SPIKE_BARE_ENDPOINT, the one
// that borrows the endpoint alone.
#ifdef SPIKE_BARE_ENDPOINT
using EndpointUnderTest = VcmlBareEndpoint;
#else
using EndpointUnderTest = VcmlEndpoint;
#endif

// socpuppet's built-in components, and the VCML-backed endpoint as
// "vcml_pcie_endpoint", with the ports `ecam`, `mmio`, `dma`, `bar0`,
// `function_dma` and `irq0` onwards.
inline socpuppet::Registry WithVcmlEndpoint() {
  socpuppet::Registry registry = socpuppet::BuiltinComponents();
  registry.Add("vcml_pcie_endpoint", [](const char* name,
                                        const socpuppet::Config& config) {
    using socpuppet::Optional;
    const VcmlEndpoint::Config endpoint{
        .vendor_id = static_cast<std::uint16_t>(
            Optional(config, "vendor_id", kVendorId)),
        .device_id = static_cast<std::uint16_t>(
            Optional(config, "device_id", kDeviceId)),
        .class_code = static_cast<std::uint32_t>(
            Optional(config, "class_code", kNvmeClassCode)),
        .function_size = Optional(config, "function_size", kFunctionSize),
        .vectors = Optional(config, "vectors", kVectors),
        .dma_by_dmi = Optional(config, "dma_by_dmi", 0) != 0};
    auto module = std::make_unique<EndpointUnderTest>(name, endpoint);
    std::vector<socpuppet::Port> ports{
        socpuppet::TargetPort("ecam", module->ecam),
        socpuppet::TargetPort("mmio", module->mmio),
        socpuppet::InitiatorPort("dma", module->dma),
        socpuppet::InitiatorPort("bar0", module->bar0),
        socpuppet::TargetPort("function_dma", module->function_dma)};
    for (std::size_t vector = 0; vector < endpoint.vectors; ++vector) {
      ports.push_back(socpuppet::WireSinkPort("irq" + std::to_string(vector),
                                              module->irq[vector]));
    }
    return socpuppet::Instance{.module = std::move(module),
                               .ports = std::move(ports)};
  });
  return registry;
}

}  // namespace spike

#endif  // SPIKES_PCIE_COMPONENTS_H_
