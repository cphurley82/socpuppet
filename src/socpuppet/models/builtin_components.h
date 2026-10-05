#ifndef SOCPUPPET_MODELS_BUILTIN_COMPONENTS_H_
#define SOCPUPPET_MODELS_BUILTIN_COMPONENTS_H_

#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <scc/router.h>

#include "socpuppet/models/dbt_rise_cpu.h"
#include "socpuppet/models/memory.h"
#include "socpuppet/models/ns16550.h"
#include "socpuppet/models/pass_through_link.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/registry.h"
#include "socpuppet/platform/slots.h"

namespace socpuppet {

static_assert(MemorySlot<Memory>);
static_assert(LinkEndpointSlot<PassThroughLinkEndpoint>);
static_assert(UartSlot<Ns16550>);
static_assert(CpuSlot<ScriptedBusMaster>);
static_assert(CpuSlot<DbtRiseCpu>);

// The registry of every component that ships with socpuppet.
inline Registry BuiltinComponents() {
  Registry registry;
  registry.Add("dbt_rise_cpu", [](const char* name, const Config& config) {
    auto module = std::make_unique<DbtRiseCpu>(
        name, Required(config, "xlen", "dbt_rise_cpu"),
        Required(config, "reset_vector", "dbt_rise_cpu"));
    std::vector<Port> ports{InitiatorPort("socket", module->socket),
                            WireSinkPort("irq", module->irq),
                            WireSinkPort("reset", module->reset)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("memory", [](const char* name, const Config& config) {
    auto module =
        std::make_unique<Memory>(name, Required(config, "size", "memory"));
    std::vector<Port> ports{TargetPort("socket", module->socket)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  registry.Add("ns16550", [](const char* name, const Config&) {
    auto module = std::make_unique<Ns16550>(name);
    std::vector<Port> ports{TargetPort("socket", module->socket)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  // One end of a link. The die's side may be left unconnected in either
  // direction; the peer side must be bound to the other endpoint.
  registry.Add(
      "pass_through_link_endpoint", [](const char* name, const Config&) {
        auto module = std::make_unique<PassThroughLinkEndpoint>(name);
        std::vector<Port> ports{
            TargetPort("target", module->target, /*required=*/false),
            InitiatorPort("initiator", module->initiator, /*required=*/false),
            InitiatorPort("peer_initiator", module->peer_initiator),
            TargetPort("peer_target", module->peer_target)};
        return Instance{.module = std::move(module), .ports = std::move(ports)};
      });
  registry.Add("scripted_bus_master", [](const char* name, const Config&) {
    auto module = std::make_unique<ScriptedBusMaster>(name);
    std::vector<Port> ports{InitiatorPort("socket", module->socket),
                            WireSinkPort("irq", module->irq),
                            WireSinkPort("reset", module->reset)};
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  // The router is SCC's (Minres SystemC-Components), not ours. This adapter
  // sizes it and loads its address map from the parameters:
  //   outputs              how many targets it routes to
  //   out<N>.base, .size   the address range routed to output N
  // An access inside a range reaches that target at its offset from the base.
  registry.Add("router", [](const char* name, const Config& config) {
    const std::uint64_t outputs = Required(config, "outputs", "router");
    auto module = std::make_unique<scc::router<32>>(name, outputs, 1);
    module->set_warn_on_address_error(true);
    std::vector<Port> ports{TargetPort("target", module->target[0])};
    for (std::uint64_t index = 0; index < outputs; ++index) {
      const std::string output = "out" + std::to_string(index);
      module->set_target_range(index,
                               Required(config, output + ".base", "router"),
                               Required(config, output + ".size", "router"));
      ports.push_back(InitiatorPort(output, module->initiator[index]));
    }
    return Instance{.module = std::move(module), .ports = std::move(ports)};
  });
  return registry;
}

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_BUILTIN_COMPONENTS_H_
