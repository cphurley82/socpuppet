#pragma once

#include <memory>

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
    std::vector<Port> ports{initiator_port("socket", module->socket)};
    return Instance{std::move(module), std::move(ports)};
  });
  return registry;
}

}  // namespace socpuppet
