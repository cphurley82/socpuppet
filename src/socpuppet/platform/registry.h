#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <systemc>

#include "socpuppet/platform/port.h"

namespace socpuppet {

// The parameters a component is created with, by name.
using Config = std::map<std::string, std::uint64_t>;

// One component in a platform: the SystemC module and its connection points.
struct Instance {
  std::unique_ptr<sc_core::sc_module> module;
  std::vector<Port> ports;
};

// The value of a parameter the implementation cannot do without.
inline std::uint64_t required(const Config& config,
                              const std::string& parameter,
                              const std::string& implementation) {
  const auto found = config.find(parameter);
  if (found == config.end()) {
    throw std::invalid_argument("A \"" + implementation + "\" needs a \"" +
                                parameter +
                                "\" parameter, and none was given.");
  }
  return found->second;
}

// Creates a component with the given instance name and parameters.
using Factory = std::function<Instance(const char* name, const Config& config)>;

// The catalogue of component implementations a platform can be built from,
// looked up by name. This is what lets Python pick an implementation per slot.
class Registry {
 public:
  void add(std::string implementation, Factory factory) {
    factories_.emplace(std::move(implementation), std::move(factory));
  }

  const Factory& find(const std::string& implementation) const {
    const auto found = factories_.find(implementation);
    if (found == factories_.end()) {
      std::string known;
      for (const auto& [name, factory] : factories_)
        known += (known.empty() ? "" : ", ") + name;
      throw std::invalid_argument("No component implementation is called \"" +
                                  implementation +
                                  "\". Known implementations: " + known + ".");
    }
    return found->second;
  }

  std::vector<std::string> implementations() const {
    std::vector<std::string> names;
    for (const auto& [name, factory] : factories_) names.push_back(name);
    return names;
  }

 private:
  std::map<std::string, Factory> factories_;
};

}  // namespace socpuppet
