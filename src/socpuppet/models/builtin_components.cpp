#include "socpuppet/models/builtin_components.h"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <scc/router.h>

#include "socpuppet/models/behavioral_nvme.h"
#include "socpuppet/models/dbt_rise_cpu.h"
#include "socpuppet/models/machine_timer.h"
#include "socpuppet/models/memory.h"
#include "socpuppet/models/msi_plic_bridge.h"
#include "socpuppet/models/msi_receiver.h"
#include "socpuppet/models/ns16550.h"
#include "socpuppet/models/pass_through_link.h"
#include "socpuppet/models/pcie_endpoint.h"
#include "socpuppet/models/pcie_root_complex.h"
#include "socpuppet/models/plic.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "socpuppet/platform/slots.h"

namespace socpuppet {

static_assert(MemorySlot<Memory>);
static_assert(LinkEndpointSlot<PassThroughLinkEndpoint>);
static_assert(UartSlot<Ns16550>);
static_assert(MachineTimerSlot<MachineTimer>);
static_assert(InterruptControllerSlot<Plic>);
static_assert(NvmeFunctionSlot<BehavioralNvme>);
static_assert(CpuSlot<ScriptedBusMaster>);
static_assert(CpuSlot<DbtRiseCpu>);

namespace {

// How many interrupt vectors a PCIe function may have, and so how many
// anything that takes its interrupt messages may. MSI-X, the capability
// that tells the host about them, has room for 2048.
constexpr Within kInterruptVectors{.least = 1, .most = 2048};

// Adds a port for each of a component's numbered lines: `prefix` and a
// number, counting up from `first`. `make_port` turns a name and a line
// into the port.
void AddNumberedPorts(std::vector<Port>& ports, const std::string& prefix,
                      std::size_t first, auto& lines, auto make_port) {
  ports.reserve(ports.size() + lines.size());
  for (std::size_t index = 0; index < lines.size(); ++index) {
    ports.push_back(
        make_port(prefix + std::to_string(first + index), lines[index]));
  }
}

}  // namespace

Registry BuiltinComponents() {
  Registry registry;
  registry.Add("behavioral_nvme", [](const char* name, Parameters& parameters) {
    const std::uint64_t vectors =
        parameters.Required("vectors", kInterruptVectors);
    auto module = std::make_unique<BehavioralNvme>(
        name, parameters.Required("blocks"), vectors);
    std::vector<Port> ports{TargetPort("bar0", module->bar0),
                            InitiatorPort("dma", module->dma)};
    // A host need not use every vector, so a line may be left unconnected.
    AddNumberedPorts(ports, "irq", 0, module->irq,
                     [](std::string port, sc_core::sc_out<bool>& line) {
                       return WireSourcePort(std::move(port), line,
                                             /*required=*/false);
                     });
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("dbt_rise_cpu", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<DbtRiseCpu>(
        name, parameters.Required("xlen"), parameters.Required("reset_vector"),
        static_cast<std::uint16_t>(
            parameters.Optional("gdb_port", 0, kFitsIn16Bits)));
    std::vector<Port> ports{InitiatorPort("socket", module->socket),
                            WireSinkPort("irq", module->irq),
                            WireSinkPort("timer_irq", module->timer_irq),
                            WireSinkPort("reset", module->reset)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("machine_timer", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<MachineTimer>(
        name, parameters.Required("frequency_hz", {.least = 1}));
    std::vector<Port> ports{TargetPort("socket", module->socket),
                            WireSourcePort("irq", module->irq)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("memory", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<Memory>(name, parameters.Required("size"));
    std::vector<Port> ports{TargetPort("socket", module->socket)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("msi_plic_bridge", [](const char* name, Parameters& parameters) {
    auto module = std::make_unique<MsiPlicBridge>(
        name, parameters.Required("vectors", kInterruptVectors));
    std::vector<Port> ports{TargetPort("socket", module->socket)};
    AddNumberedPorts(ports, "irq", 0, module->irq,
                     [](std::string port, sc_core::sc_out<bool>& line) {
                       return WireSourcePort(std::move(port), line);
                     });
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("msi_receiver", [](const char* name, Parameters&) {
    auto module = std::make_unique<MsiReceiver>(name);
    std::vector<Port> ports{TargetPort("socket", module->socket),
                            WireSourcePort("irq", module->irq)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("ns16550", [](const char* name, Parameters&) {
    auto module = std::make_unique<Ns16550>(name);
    std::vector<Port> ports{TargetPort("socket", module->socket)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  // One end of a link. The die's side may be left unconnected in either
  // direction; the peer side must be bound to the other endpoint.
  registry.Add("pass_through_link_endpoint", [](const char* name, Parameters&) {
    auto module = std::make_unique<PassThroughLinkEndpoint>(name);
    std::vector<Port> ports{
        TargetPort("target", module->target, /*required=*/false),
        InitiatorPort("initiator", module->initiator, /*required=*/false),
        InitiatorPort("peer_initiator", module->peer_initiator),
        TargetPort("peer_target", module->peer_target)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("pcie_endpoint", [](const char* name, Parameters& parameters) {
    const std::uint64_t vectors =
        parameters.Required("vectors", kInterruptVectors);
    auto module = std::make_unique<PcieEndpoint>(
        name,
        PcieEndpointRegisters::Identity{
            .vendor_id = static_cast<std::uint16_t>(
                parameters.Required("vendor_id", kFitsIn16Bits)),
            .device_id = static_cast<std::uint16_t>(
                parameters.Required("device_id", kFitsIn16Bits)),
            .class_code = static_cast<std::uint32_t>(
                parameters.Required("class_code", kFitsIn24Bits))},
        parameters.Required("function_size"), vectors);
    std::vector<Port> ports{TargetPort("from_host", module->from_host),
                            InitiatorPort("to_host", module->to_host),
                            InitiatorPort("bar0", module->bar0),
                            TargetPort("dma", module->dma)};
    AddNumberedPorts(ports, "irq", 0, module->irq, WireSinkPort);
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add(
      "pcie_root_complex", [](const char* name, Parameters& parameters) {
        auto module = std::make_unique<PcieRootComplex>(
            name, parameters.Required("mmio_base"));
        std::vector<Port> ports{TargetPort("ecam", module->ecam),
                                TargetPort("mmio", module->mmio),
                                InitiatorPort("dma", module->dma),
                                InitiatorPort("to_device", module->to_device),
                                TargetPort("from_device", module->from_device)};
        return Instance{.module = std::move(module), .ports = std::move(ports)};
      });
  // Its sources are ports "source1" to "source31", numbered as the PLIC
  // numbers them.
  registry.Add("plic", [](const char* name, Parameters&) {
    auto module = std::make_unique<Plic>(name);
    std::vector<Port> ports{TargetPort("socket", module->socket),
                            WireSourcePort("irq", module->irq)};
    AddNumberedPorts(ports, "source", 1, module->sources, WireSinkPort);
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("scripted_bus_master", [](const char* name, Parameters&) {
    auto module = std::make_unique<ScriptedBusMaster>(name);
    std::vector<Port> ports{InitiatorPort("socket", module->socket),
                            WireSinkPort("irq", module->irq),
                            WireSinkPort("timer_irq", module->timer_irq),
                            WireSinkPort("reset", module->reset)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  // The router is SCC's (Minres SystemC-Components), not ours. This adapter
  // sizes it and loads its address map from the parameters:
  //   inputs               how many masters it takes; one if left out
  //   outputs              how many targets it routes to
  //   out<N>.base, .size   the address range routed to output N
  // An access inside a range reaches that target at its offset from the base,
  // whichever input it came in by. The first input is the port `target`, and
  // the others are `in1`, `in2` and so on.
  registry.Add("router", [](const char* name, Parameters& parameters) {
    const std::uint64_t inputs = parameters.Optional("inputs", 1);
    const std::uint64_t outputs = parameters.Required("outputs");
    auto module = std::make_unique<scc::router<32>>(name, outputs, inputs);
    module->set_warn_on_address_error(true);
    std::vector<Port> ports;
    ports.reserve(inputs + outputs);
    for (std::uint64_t index = 0; index < inputs; ++index) {
      ports.push_back(TargetPort(
          index == 0 ? std::string{"target"} : "in" + std::to_string(index),
          module->target[index]));
    }
    for (std::uint64_t index = 0; index < outputs; ++index) {
      const std::string output = "out" + std::to_string(index);
      module->set_target_range(index, parameters.Required(output + ".base"),
                               parameters.Required(output + ".size"));
      ports.push_back(InitiatorPort(output, module->initiator[index]));
    }
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  return registry;
}

}  // namespace socpuppet
