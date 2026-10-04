#pragma once

#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>

#include <systemc>
#include <tlm>

#include "socpuppet/platform/registry.h"

namespace socpuppet {

// A platform under construction: components created by implementation name
// and wired together by port name.
//
// Names are dotted paths. In "io.ram", "io" is a group (a die, say) and
// "ram" is the component inside it; the same path names the component in
// the simulation, in traces and in error messages.
class Platform {
 public:
  explicit Platform(Registry registry) : registry_(std::move(registry)) {}

  void add(const std::string& path, const std::string& implementation,
           const Config& config = {}) {
    const Factory& create = registry_.find(implementation);
    if (instances_.contains(path)) {
      throw std::invalid_argument("There is already a component called \"" + path +
                                  "\". Each component needs its own name.");
    }
    instances_.emplace(path, inside_parent(path, [&](const char* name) {
                         return create(name, config);
                       }));
  }

  // Binds two ports, each named "<component path>.<port>". The first must
  // be a source (a TLM initiator socket) and the second a sink (a target).
  void bind(const std::string& source, const std::string& sink) {
    const Port& from = port(source);
    const Port& to = port(sink);
    if (from.role != Port::Role::source || to.role != Port::Role::sink) {
      throw std::invalid_argument(
          "Cannot bind \"" + source + "\" to \"" + sink +
          "\": the first must be a source (such as a TLM initiator socket) and the second "
          "a sink (such as a TLM target socket).");
    }
    dynamic_cast<tlm::tlm_initiator_socket<>&>(*from.socket)
        .bind(dynamic_cast<tlm::tlm_target_socket<>&>(*to.socket));
    bound_.insert(from.socket);
    bound_.insert(to.socket);
  }

  // Checks that every port is bound. SystemC would also object to an unbound
  // port, but only once the simulation starts and in its own terms.
  void check_wiring() {
    std::string unbound;
    for (const auto& [path, instance] : instances_) {
      for (const Port& candidate : instance.ports) {
        if (!bound_.contains(candidate.socket)) {
          unbound += (unbound.empty() ? "" : ", ") + path + "." + candidate.name;
        }
      }
    }
    if (!unbound.empty()) {
      throw std::runtime_error("These ports are not bound to anything: " + unbound +
                               ". Bind every port before the simulation starts.");
    }
  }

  // The component at `path`, as its concrete C++ type. An escape hatch for
  // C++ callers that need more than composing by name offers.
  template <typename Module>
  Module& module(const std::string& path) {
    return dynamic_cast<Module&>(*instance(path).module);
  }

 private:
  // A level of naming with no behavior of its own.
  struct Group : sc_core::sc_module {
    explicit Group(const sc_core::sc_module_name& name) : sc_module(name) {}
    // While the returned scope is alive, new modules become children of
    // this group. SystemC 3.0 allows that outside a constructor.
    sc_core::sc_hierarchy_scope enter() { return get_hierarchy_scope(); }
  };

  // Calls make(leaf name) inside the group that `path` puts it in, so that
  // SystemC names the new module by its full path.
  template <typename Make>
  auto inside_parent(const std::string& path, Make make) -> decltype(make("")) {
    const auto dot = path.rfind('.');
    if (dot == std::string::npos) return make(path.c_str());
    sc_core::sc_hierarchy_scope scope = group(path.substr(0, dot)).enter();
    return make(path.substr(dot + 1).c_str());
  }

  Group& group(const std::string& path) {
    auto& found = groups_[path];
    if (!found) {
      found = inside_parent(path, [](const char* name) { return std::make_unique<Group>(name); });
    }
    return *found;
  }

  Instance& instance(const std::string& path) {
    const auto found = instances_.find(path);
    if (found == instances_.end()) {
      std::string known;
      for (const auto& [name, each] : instances_) known += (known.empty() ? "" : ", ") + name;
      throw std::invalid_argument("There is no component called \"" + path +
                                  "\". The components are: " + known + ".");
    }
    return found->second;
  }

  const Port& port(const std::string& path) {
    const auto dot = path.rfind('.');
    const std::string component = path.substr(0, dot);
    const std::string name = path.substr(dot + 1);
    std::string known;
    for (const Port& candidate : instance(component).ports) {
      if (candidate.name == name) return candidate;
      known += (known.empty() ? "" : ", ") + candidate.name;
    }
    throw std::invalid_argument("\"" + component + "\" has no port called \"" + name +
                                "\" (asked for \"" + path + "\"). Its ports are: " + known + ".");
  }

  Registry registry_;
  // Groups are declared before instances so they outlive the components
  // built inside them.
  std::map<std::string, std::unique_ptr<Group>> groups_;
  std::map<std::string, Instance> instances_;
  std::set<const sc_core::sc_object*> bound_;
};

}  // namespace socpuppet
