#ifndef SOCPUPPET_PLATFORM_REGISTRY_H_
#define SOCPUPPET_PLATFORM_REGISTRY_H_

#include <cstdint>
#include <format>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <set>
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

// The values a parameter may take, both ends included.
struct Within {
  std::uint64_t least = 0;
  std::uint64_t most = std::numeric_limits<std::uint64_t>::max();
};
// What fits in a register field of so many bits.
inline constexpr Within kFitsIn16Bits{.most = 0xFFFF};
inline constexpr Within kFitsIn24Bits{.most = 0xFF'FFFF};

// What a factory reads its parameters from. It knows which implementation
// is asking, so that an error can say, and it notes each name asked for,
// so that a parameter no one asked for (a misspelling, say) is refused
// and not quietly ignored.
class Parameters {
 public:
  Parameters(std::string implementation, const Config& config)
      : implementation_(std::move(implementation)), config_(config) {}

  // The value of a parameter the implementation cannot do without.
  std::uint64_t Required(const std::string& parameter, Within range = {}) {
    const auto found = Find(parameter);
    if (found == config_.end()) {
      throw std::invalid_argument(
          std::format("A \"{}\" needs a \"{}\" parameter, and none was given.",
                      implementation_, parameter));
    }
    return Checked(parameter, found->second, range);
  }

  // The value of a parameter that may be left out.
  std::uint64_t Optional(const std::string& parameter, std::uint64_t otherwise,
                         Within range = {}) {
    const auto found = Find(parameter);
    return found == config_.end() ? otherwise
                                  : Checked(parameter, found->second, range);
  }

  // Throws if a parameter was given that the factory never asked for.
  void RefuseTheRest() const {
    for (const auto& [parameter, value] : config_) {
      if (asked_for_.contains(parameter)) continue;
      std::string takes;
      for (const std::string& name : asked_for_) {
        takes += (takes.empty() ? "\"" : ", \"") + name + "\"";
      }
      throw std::invalid_argument(std::format(
          "A \"{}\" has no \"{}\" parameter. {}", implementation_, parameter,
          takes.empty() ? "It takes none."
                        : "The ones it takes are: " + takes + "."));
    }
  }

 private:
  Config::const_iterator Find(const std::string& parameter) {
    asked_for_.insert(parameter);
    return config_.find(parameter);
  }

  std::uint64_t Checked(const std::string& parameter, std::uint64_t value,
                        Within range) const {
    if (value < range.least || value > range.most) {
      throw std::invalid_argument(std::format(
          "A \"{}\" takes a \"{}\" from {} to {}, and {} was given.",
          implementation_, parameter, range.least, range.most, value));
    }
    return value;
  }

  std::string implementation_;
  const Config& config_;
  std::set<std::string> asked_for_;
};

// Creates a component with the given instance name and parameters.
using Factory =
    std::function<Instance(const char* name, Parameters& parameters)>;

// The catalogue of component implementations a platform can be built from,
// looked up by name. This is what lets Python pick an implementation per slot.
class Registry {
 public:
  void Add(std::string implementation, Factory factory) {
    factories_.emplace(std::move(implementation), std::move(factory));
  }

  // Creates a component of the named implementation. Throws if there is
  // no such implementation, or if it does not accept the parameters.
  Instance Create(const std::string& implementation, const char* name,
                  const Config& config) const {
    Parameters parameters{implementation, config};
    Instance instance = Find(implementation)(name, parameters);
    parameters.RefuseTheRest();
    return instance;
  }

  std::vector<std::string> Implementations() const {
    std::vector<std::string> names;
    names.reserve(factories_.size());
    for (const auto& [name, factory] : factories_) names.push_back(name);
    return names;
  }

 private:
  const Factory& Find(const std::string& implementation) const {
    const auto found = factories_.find(implementation);
    if (found == factories_.end()) {
      std::string known;
      for (const auto& [name, factory] : factories_) {
        known += (known.empty() ? "" : ", ") + name;
      }
      throw std::invalid_argument("No component implementation is called \"" +
                                  implementation +
                                  "\". Known implementations: " + known + ".");
    }
    return found->second;
  }

  std::map<std::string, Factory> factories_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_REGISTRY_H_
