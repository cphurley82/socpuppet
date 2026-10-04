#pragma once

#include <memory>
#include <string>

#include <scc/router.h>

#include "socpuppet/models/memory.h"
#include "socpuppet/models/pass_through_link.h"
#include "socpuppet/models/scripted_bus_master.h"
#include "socpuppet/platform/registry.h"

namespace socpuppet {

// The registry of every component that ships with socpuppet.
inline Registry builtin_components() {
  Registry registry;
  registry.add("memory", [](const char* name, const Config& config) {
    auto module = std::make_unique<Memory>(name, required(config, "size", "memory"));
    std::vector<Port> ports{target_port("socket", module->socket)};
    return Instance{std::move(module), std::move(ports)};
  });
  registry.add("pass_through_link", [](const char* name, const Config&) {
    auto module = std::make_unique<PassThroughLink>(name);
    std::vector<Port> ports{target_port("target", module->target),
                            initiator_port("initiator", module->initiator)};
    return Instance{std::move(module), std::move(ports)};
  });
  registry.add("scripted_bus_master", [](const char* name, const Config&) {
    auto module = std::make_unique<ScriptedBusMaster>(name);
    std::vector<Port> ports{initiator_port("socket", module->socket),
                            wire_sink_port("irq", module->irq),
                            wire_sink_port("reset", module->reset)};
    return Instance{std::move(module), std::move(ports)};
  });
  // The router is SCC's (Minres SystemC-Components), not ours. This adapter
  // sizes it and loads its address map from the parameters:
  //   outputs              how many targets it routes to
  //   out<N>.base, .size   the address range routed to output N
  // An access inside a range reaches that target at its offset from the base.
  registry.add("router", [](const char* name, const Config& config) {
    const std::uint64_t outputs = required(config, "outputs", "router");
    auto module = std::make_unique<scc::router<32>>(name, outputs, 1);
    module->set_warn_on_address_error(true);
    std::vector<Port> ports{target_port("target", module->target[0])};
    for (std::uint64_t index = 0; index < outputs; ++index) {
      const std::string output = "out" + std::to_string(index);
      module->set_target_range(index, required(config, output + ".base", "router"),
                               required(config, output + ".size", "router"));
      ports.push_back(initiator_port(output, module->initiator[index]));
    }
    return Instance{std::move(module), std::move(ports)};
  });
  return registry;
}

}  // namespace socpuppet
