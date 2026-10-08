#include "socpuppet/platform/platform.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <format>
#include <memory>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <typeinfo>
#include <utility>
#include <variant>
#include <vector>

#include <cxxabi.h>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/platform/failure.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

namespace {

// Lets std::visit pick a lambda by the types a variant holds.
template <typename... Lambdas>
struct Overloaded : Lambdas... {
  using Lambdas::operator()...;
};
template <typename... Lambdas>
Overloaded(Lambdas...) -> Overloaded<Lambdas...>;

// What an optional bus port is bound to when nobody connected it, since
// SystemC insists that every socket be bound to something.
//
// An access sent out of an unconnected initiator ends up here and gets an
// address-error response.
struct NothingThere : sc_core::sc_module {
  tlm_utils::simple_target_socket<NothingThere> socket{"socket"};
  explicit NothingThere(const sc_core::sc_module_name& name) : sc_module(name) {
    socket.register_b_transport(this, &NothingThere::b_transport);
  }
  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
  }
};

// An unconnected target is bound to this, which never sends anything.
struct NobodyThere : sc_core::sc_module {
  tlm_utils::simple_initiator_socket<NobodyThere> socket{"socket"};
  explicit NobodyThere(const sc_core::sc_module_name& name) : sc_module(name) {}
};

// A dotted path as a single SystemC name: "io.ram" becomes "io_ram".
std::string FlatName(std::string path) {
  std::ranges::replace(path, '.', '_');
  return path;
}

// A C++ type's name as it is written in the source. The compiler's own
// spelling of it is all there is to go on, and both of the compilers this
// builds with can turn that back.
std::string NameOf(const std::type_info& type) {
  int status = 0;
  const std::unique_ptr<char, void (*)(void*)> name{
      abi::__cxa_demangle(type.name(), nullptr, nullptr, &status), std::free};
  return status == 0 ? name.get() : type.name();
}

// Why two ports that are not a source and a sink of one kind cannot be
// bound.
std::invalid_argument CannotBind(const std::string& source, const Port& from,
                                 const std::string& sink, const Port& to) {
  if (KindOf(from) != KindOf(to)) {
    return std::invalid_argument(std::format(
        R"(Cannot bind "{}" to "{}": the first is a {} port and the second )"
        "is a {} port.",
        source, sink, ToString(KindOf(from)), ToString(KindOf(to))));
  }
  return std::invalid_argument(std::format(
      R"(Cannot bind "{}" to "{}": the first must be a source (a TLM )"
      "initiator socket, or the port driving a wire) and the second a sink "
      "(a TLM target socket, or a port reading a wire).",
      source, sink));
}

}  // namespace

struct Platform::Group : sc_core::sc_module {
  explicit Group(const sc_core::sc_module_name& name) : sc_module(name) {}
  // While the returned scope is alive, new modules become children of
  // this group. SystemC 3.0 allows that outside a constructor.
  sc_core::sc_hierarchy_scope Enter() { return get_hierarchy_scope(); }
};

Platform::Platform(Registry registry) : registry_(std::move(registry)) {}

Platform::~Platform() = default;

void Platform::Add(const std::string& path, const std::string& implementation,
                   const Config& config) {
  RefuseOnceElaborated("add a component");
  if (instances_.contains(path)) {
    throw std::invalid_argument("There is already a component called \"" +
                                path +
                                "\". Each component needs its own name.");
  }
  instances_.emplace(path, InsideParent(path, [&](const char* name) {
                       return registry_.Create(implementation, name, config);
                     }));
}

void Platform::Bind(const std::string& source, const std::string& sink,
                    bool traced) {
  RefuseOnceElaborated("bind ports");
  const Port& from = PortAt(source);
  const Port& to = PortAt(sink);
  std::visit(
      Overloaded{
          [&](Port::Initiator initiator, Port::Target target) {
            BindBus(*initiator, *target, source, sink, traced);
          },
          [&](Port::WireSource driver, Port::WireSink reader) {
            if (traced) {
              throw std::invalid_argument(std::format(
                  R"(Cannot trace the connection from "{}" to "{}": only a )"
                  "bus connection can be traced, and this is a wire.",
                  source, sink));
            }
            reader->bind(WireDrivenBy(*driver, source));
          },
          [&](auto, auto) { throw CannotBind(source, from, sink, to); }},
      from.connector, to.connector);
  bound_.insert(ObjectOf(from));
  bound_.insert(ObjectOf(to));
}

void Platform::BindBus(tlm::tlm_initiator_socket<>& initiator,
                       tlm::tlm_target_socket<>& target,
                       const std::string& source, const std::string& sink,
                       bool traced) {
  if (!traced) {
    initiator.bind(target);
    return;
  }
  Tracer& tracer = *tracers_.emplace_back(std::make_unique<Tracer>(
      FlatName(source + ".trace").c_str(), source, sink, trace_));
  initiator.bind(tracer.target);
  tracer.initiator.bind(target);
}

void Platform::SetQuantum(const sc_core::sc_time& quantum) {
  tlm::tlm_global_quantum::instance().set(quantum);
}

void Platform::Elaborate() {
  RefuseOnceElaborated("elaborate it again");
  CheckWiring();
  TieOffUnconnectedPorts();
  // sc_start() does exactly this as its first step. Calling it here is not
  // part of the SystemC standard, but the reference kernel exposes it.
  sc_core::sc_get_curr_simcontext()->initialize(true);
  elaborated_ = true;
}

void Platform::Run() {
  RefuseUnlessElaborated("run");
  sc_core::sc_start();
  RethrowParkedFailure();
}

void Platform::Run(const sc_core::sc_time& duration) {
  RefuseUnlessElaborated("run");
  sc_core::sc_start(duration);
  RethrowParkedFailure();
}

bool Platform::Step() {
  RefuseUnlessElaborated("step");
  const std::optional<sc_core::sc_time> ahead = TimeToNextActivity();
  if (!ahead) return false;
  Run(*ahead);
  FinishThisMoment();
  return true;
}

std::optional<sc_core::sc_time> Platform::TimeToNextActivity() {
  RefuseUnlessElaborated("look for its next activity");
  FinishThisMoment();
  if (!sc_core::sc_pending_activity()) return std::nullopt;
  return sc_core::sc_time_to_pending_activity();
}

sc_core::sc_time Platform::Time() const { return sc_core::sc_time_stamp(); }

bool Platform::DebugRead(const std::string& via, std::uint64_t address,
                         std::span<std::byte> data) {
  return Debug(tlm::TLM_READ_COMMAND, via, address,
               {reinterpret_cast<std::uint8_t*>(data.data()), data.size()});
}

bool Platform::DebugWrite(const std::string& via, std::uint64_t address,
                          std::span<const std::byte> data) {
  return Debug(tlm::TLM_WRITE_COMMAND, via, address,
               WriteData({reinterpret_cast<const std::uint8_t*>(data.data()),
                          data.size()}));
}

const std::vector<Port>& Platform::Ports(const std::string& path) {
  return InstanceAt(path).ports;
}

void Platform::RefuseOnceElaborated(const char* attempt) const {
  if (!elaborated_) return;
  throw std::logic_error(std::format(
      "Cannot {}: the platform is elaborated, and what it is made of is "
      "fixed from then on. Add and bind everything before Elaborate().",
      attempt));
}

void Platform::RefuseUnlessElaborated(const char* attempt) const {
  if (elaborated_) return;
  throw std::logic_error(std::format(
      "Cannot {} a platform that is not elaborated yet. Call Elaborate() "
      "first.",
      attempt));
}

void Platform::TieOffUnconnectedPorts() {
  for (auto& [path, instance] : instances_) {
    for (const Port& each : instance.ports) {
      if (bound_.contains(ObjectOf(each))) continue;
      std::visit(Overloaded{[&](Port::Initiator initiator) {
                              auto tie_off = std::make_unique<NothingThere>(
                                  sc_core::sc_gen_unique_name("unconnected"));
                              initiator->bind(tie_off->socket);
                              tie_offs_.push_back(std::move(tie_off));
                            },
                            [&](Port::Target target) {
                              auto tie_off = std::make_unique<NobodyThere>(
                                  sc_core::sc_gen_unique_name("unconnected"));
                              tie_off->socket.bind(*target);
                              tie_offs_.push_back(std::move(tie_off));
                            },
                            // A wire output gets a wire that nobody reads.
                            [&](Port::WireSource driver) {
                              WireDrivenBy(*driver, path + "." + each.name);
                            },
                            // A wire input needs nothing here: its component
                            // ties itself low (see WireSinkPort).
                            [](Port::WireSink) {}},
                 each.connector);
    }
  }
}

void Platform::FinishThisMoment() {
  while (sc_core::sc_pending_activity_at_current_time()) {
    Run(sc_core::SC_ZERO_TIME);
  }
}

void Platform::CheckWiring() const {
  std::string unbound;
  for (const auto& [path, instance] : instances_) {
    for (const Port& candidate : instance.ports) {
      if (candidate.required && !bound_.contains(ObjectOf(candidate))) {
        unbound += (unbound.empty() ? "" : ", ") + path + "." + candidate.name;
      }
    }
  }
  if (!unbound.empty()) {
    throw std::runtime_error(
        "These ports are not bound to anything: " + unbound +
        ". Bind every port before the simulation starts.");
  }
}

bool Platform::Debug(tlm::tlm_command command, const std::string& via,
                     std::uint64_t address, std::span<std::uint8_t> data) {
  RefuseUnlessElaborated("make a debug access to");
  const Port& view = PortAt(via);
  const Port::Initiator* socket = std::get_if<Port::Initiator>(&view.connector);
  if (socket == nullptr) {
    throw std::invalid_argument(std::format(
        "A debug access looks at the platform through a bus source port "
        "(such as a bus master's initiator socket), and \"{}\" is a {} {}.",
        via, ToString(KindOf(view)),
        RoleOf(view) == Port::Role::kSource ? "source" : "sink"));
  }
  return DebugTransport(**socket, command, address, data) == data.size();
}

Platform::Wire& Platform::WireDrivenBy(sc_core::sc_out<bool>& source,
                                       const std::string& path) {
  auto& wire = wires_[&source];
  if (!wire) {
    wire = std::make_unique<Wire>(FlatName(path).c_str());
    source.bind(*wire);
  }
  return *wire;
}

template <typename Make>
auto Platform::InsideParent(const std::string& path, Make make)
    -> decltype(make("")) {
  const auto dot = path.rfind('.');
  if (dot == std::string::npos) return make(path.c_str());
  sc_core::sc_hierarchy_scope scope = GroupAt(path.substr(0, dot)).Enter();
  return make(path.substr(dot + 1).c_str());
}

Platform::Group& Platform::GroupAt(const std::string& path) {
  auto& found = groups_[path];
  if (!found) {
    found = InsideParent(
        path, [](const char* name) { return std::make_unique<Group>(name); });
  }
  return *found;
}

Instance& Platform::InstanceAt(const std::string& path) {
  const auto found = instances_.find(path);
  if (found == instances_.end()) {
    std::string known;
    for (const auto& [name, each] : instances_) {
      known += (known.empty() ? "" : ", ") + name;
    }
    throw std::invalid_argument("There is no component called \"" + path +
                                "\". The components are: " + known + ".");
  }
  return found->second;
}

const Port& Platform::PortAt(const std::string& path) {
  const auto dot = path.rfind('.');
  if (dot == std::string::npos) {
    throw std::invalid_argument(std::format(
        R"("{}" does not name a port. A port is named by its component and )"
        R"(its own name with a dot between them, as in "cpu.socket".)",
        path));
  }
  const std::string component = path.substr(0, dot);
  const std::string name = path.substr(dot + 1);
  std::string known;
  for (const Port& candidate : InstanceAt(component).ports) {
    if (candidate.name == name) return candidate;
    known += (known.empty() ? "" : ", ") + candidate.name;
  }
  throw std::invalid_argument("\"" + component + "\" has no port called \"" +
                              name + "\" (asked for \"" + path +
                              "\"). Its ports are: " + known + ".");
}

std::invalid_argument Platform::NotOfThatType(const std::string& path,
                                              const std::type_info& is,
                                              const std::type_info& wanted) {
  return std::invalid_argument(
      std::format("The component \"{}\" is a {}, and it was asked for as a {}.",
                  path, NameOf(is), NameOf(wanted)));
}

}  // namespace socpuppet
