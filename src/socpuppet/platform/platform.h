#ifndef SOCPUPPET_PLATFORM_PLATFORM_H_
#define SOCPUPPET_PLATFORM_PLATFORM_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <span>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/trace.h"
#include "socpuppet/platform/failure.h"
#include "socpuppet/platform/registry.h"
#include "socpuppet/platform/tracer.h"

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

  void Add(const std::string& path, const std::string& implementation,
           const Config& config = {}) {
    const Factory& create = registry_.Find(implementation);
    if (instances_.contains(path)) {
      throw std::invalid_argument("There is already a component called \"" +
                                  path +
                                  "\". Each component needs its own name.");
    }
    instances_.emplace(path, InsideParent(path, [&](const char* name) {
                         return create(name, config);
                       }));
  }

  // Binds two ports, each named "<component path>.<port>". The first must
  // be a source (a TLM initiator socket, or a wire's driver) and the second
  // a sink (a TLM target socket, or a wire's reader), both of one kind.
  //
  // A traced bus connection gets a Tracer in the middle, which records every
  // transaction that crosses it (see RecordedTrace()).
  void Bind(const std::string& source, const std::string& sink,
            bool traced = false) {
    const Port& from = PortAt(source);
    const Port& to = PortAt(sink);
    if (from.kind != to.kind) {
      throw std::invalid_argument(
          "Cannot bind \"" + source + "\" to \"" + sink +
          "\": the first is a " + ToString(from.kind) +
          " port and the second is a " + ToString(to.kind) + " port.");
    }
    if (from.role != Port::Role::kSource || to.role != Port::Role::kSink) {
      throw std::invalid_argument("Cannot bind \"" + source + "\" to \"" +
                                  sink +
                                  "\": the first must be a source (a TLM "
                                  "initiator socket, or the port driving a "
                                  "wire) and the second a sink (a TLM target "
                                  "socket, or a port reading a wire).");
    }
    if (traced && from.kind != Port::Kind::kBus) {
      throw std::invalid_argument(
          "Cannot trace the connection from \"" + source + "\" to \"" + sink +
          "\": only a bus connection can be traced, and this "
          "is a wire.");
    }
    if (from.kind == Port::Kind::kBus) {
      auto& initiator =
          dynamic_cast<tlm::tlm_initiator_socket<>&>(*from.object);
      auto& target = dynamic_cast<tlm::tlm_target_socket<>&>(*to.object);
      if (traced) {
        Tracer& tracer = *tracers_.emplace_back(std::make_unique<Tracer>(
            FlatName(source + ".trace").c_str(), source, sink, trace_));
        initiator.bind(tracer.target);
        tracer.initiator.bind(target);
      } else {
        initiator.bind(target);
      }
    } else {
      dynamic_cast<sc_core::sc_in<bool>&>(*to.object)
          .bind(WireDrivenBy(from, source));
    }
    bound_.insert(from.object);
    bound_.insert(to.object);
  }

  // Sets the global quantum: how far a bus master may run ahead of the
  // simulation's clock before it has to let the clock catch up. That
  // running ahead is called temporal decoupling, and it is where a
  // simulation's speed comes from: a CPU model executes thousands of
  // instructions in one go, without handing control back after each. The
  // price is that others see what it did up to a quantum late.
  //
  // Zero, the default, means no running ahead at all. SystemC keeps one
  // quantum for the whole process. Call before Elaborate(); a change during
  // a run takes effect at each master's next sync.
  void SetQuantum(const sc_core::sc_time& quantum) {
    tlm::tlm_global_quantum::instance().set(quantum);
  }

  // Finishes construction: checks the wiring, then has SystemC complete its
  // elaboration (resolving every binding) and get ready to simulate, without
  // running any process yet. After this, debug accesses work and the
  // topology is fixed.
  void Elaborate() {
    CheckWiring();
    TieOffUnconnectedBusPorts();
    // sc_start() does exactly this as its first step. Calling it here is not
    // part of the SystemC standard, but the reference kernel exposes it.
    sc_core::sc_get_curr_simcontext()->initialize(true);
  }

  // Runs until nothing is left to do. Call Elaborate() first. Throws if a
  // model stopped the simulation with an error (see failure.h).
  void Run() {
    sc_core::sc_start();
    RethrowParkedFailure();
  }

  // Runs for `duration` of simulated time. Call Elaborate() first.
  void Run(const sc_core::sc_time& duration) {
    sc_core::sc_start(duration);
    RethrowParkedFailure();
  }

  // Moves to the next moment at which anything is scheduled and lets
  // everything scheduled for that moment happen. Returns false, having done
  // nothing more than finish the current moment, if nothing further is
  // scheduled.
  bool Step() {
    const std::optional<sc_core::sc_time> ahead = TimeToNextActivity();
    if (!ahead) return false;
    Run(*ahead);
    FinishThisMoment();
    return true;
  }

  // How far away the next scheduled activity is, once everything scheduled
  // for the current moment has happened. Nothing, if nothing is scheduled.
  std::optional<sc_core::sc_time> TimeToNextActivity() {
    FinishThisMoment();
    if (!sc_core::sc_pending_activity()) return std::nullopt;
    return sc_core::sc_time_to_pending_activity();
  }

  // Everything recorded on traced connections so far.
  const Trace& RecordedTrace() const { return trace_; }

  // The current simulated time.
  sc_core::sc_time Time() const { return sc_core::sc_time_stamp(); }

  // Debug accesses as seen from an initiator port: no simulated time passes
  // and nothing in the platform notices, the way a debugger reads memory.
  // Each returns false if nothing at that address took the access.
  bool DebugRead(const std::string& via, std::uint64_t address,
                 std::span<std::byte> data) {
    return Debug(tlm::TLM_READ_COMMAND, via, address, data.data(), data.size());
  }

  bool DebugWrite(const std::string& via, std::uint64_t address,
                  std::span<const std::byte> data) {
    return Debug(tlm::TLM_WRITE_COMMAND, via, address,
                 const_cast<std::byte*>(data.data()), data.size());
  }

  // The names of the ports of the component at `path`.
  std::vector<std::string> Ports(const std::string& path) {
    std::vector<std::string> names;
    for (const Port& each : InstanceAt(path).ports) names.push_back(each.name);
    return names;
  }

  // The component at `path`, as its concrete C++ type. An escape hatch for
  // C++ callers that need more than composing by name offers.
  template <typename Module>
  Module& ModuleAt(const std::string& path) {
    return dynamic_cast<Module&>(*InstanceAt(path).module);
  }

 private:
  // A level of naming with no behavior of its own.
  struct Group : sc_core::sc_module {
    explicit Group(const sc_core::sc_module_name& name) : sc_module(name) {}
    // While the returned scope is alive, new modules become children of
    // this group. SystemC 3.0 allows that outside a constructor.
    sc_core::sc_hierarchy_scope Enter() { return get_hierarchy_scope(); }
  };

  // Calls make(leaf name) inside the group that `path` puts it in, so that
  // SystemC names the new module by its full path.
  template <typename Make>
  auto InsideParent(const std::string& path, Make make) -> decltype(make("")) {
    const auto dot = path.rfind('.');
    if (dot == std::string::npos) return make(path.c_str());
    sc_core::sc_hierarchy_scope scope = GroupAt(path.substr(0, dot)).Enter();
    return make(path.substr(dot + 1).c_str());
  }

  // What an optional bus port is bound to when nobody connected it, since
  // SystemC insists that every socket be bound to something.
  //
  // An access sent out of an unconnected initiator ends up here and gets an
  // address-error response.
  struct NothingThere : sc_core::sc_module {
    tlm_utils::simple_target_socket<NothingThere> socket{"socket"};
    explicit NothingThere(const sc_core::sc_module_name& name)
        : sc_module(name) {
      socket.register_b_transport(this, &NothingThere::b_transport);
    }
    void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
      transaction.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
    }
  };
  // An unconnected target is bound to this, which never sends anything.
  struct NobodyThere : sc_core::sc_module {
    tlm_utils::simple_initiator_socket<NobodyThere> socket{"socket"};
    explicit NobodyThere(const sc_core::sc_module_name& name)
        : sc_module(name) {}
  };

  void TieOffUnconnectedBusPorts() {
    for (auto& [path, instance] : instances_) {
      for (const Port& each : instance.ports) {
        if (each.kind != Port::Kind::kBus || bound_.contains(each.object)) {
          continue;
        }
        const char* name = sc_core::sc_gen_unique_name("unconnected");
        if (each.role == Port::Role::kSource) {
          auto tie_off = std::make_unique<NothingThere>(name);
          dynamic_cast<tlm::tlm_initiator_socket<>&>(*each.object)
              .bind(tie_off->socket);
          tie_offs_.push_back(std::move(tie_off));
        } else {
          auto tie_off = std::make_unique<NobodyThere>(name);
          tie_off->socket.bind(
              dynamic_cast<tlm::tlm_target_socket<>&>(*each.object));
          tie_offs_.push_back(std::move(tie_off));
        }
      }
    }
  }

  // Runs delta cycles until nothing more is scheduled for the current time.
  void FinishThisMoment() {
    while (sc_core::sc_pending_activity_at_current_time()) {
      Run(sc_core::SC_ZERO_TIME);
    }
  }

  // SystemC would also object to an unbound port, but only once the
  // simulation starts and in its own terms.
  void CheckWiring() {
    std::string unbound;
    for (const auto& [path, instance] : instances_) {
      for (const Port& candidate : instance.ports) {
        if (candidate.required && !bound_.contains(candidate.object)) {
          unbound +=
              (unbound.empty() ? "" : ", ") + path + "." + candidate.name;
        }
      }
    }
    if (!unbound.empty()) {
      throw std::runtime_error(
          "These ports are not bound to anything: " + unbound +
          ". Bind every port before the simulation starts.");
    }
  }

  bool Debug(tlm::tlm_command command, const std::string& via,
             std::uint64_t address, std::byte* data, std::size_t length) {
    tlm::tlm_generic_payload transaction;
    transaction.set_command(command);
    transaction.set_address(address);
    transaction.set_data_ptr(reinterpret_cast<unsigned char*>(data));
    transaction.set_data_length(static_cast<unsigned>(length));
    transaction.set_streaming_width(static_cast<unsigned>(length));
    const Port& view = PortAt(via);
    if (view.kind != Port::Kind::kBus || view.role != Port::Role::kSource) {
      throw std::invalid_argument(
          "A debug access looks at the platform through a bus source port "
          "(such as a bus "
          "master's initiator socket), and \"" +
          via + "\" is a " + ToString(view.kind) +
          (view.role == Port::Role::kSource ? " source." : " sink."));
    }
    auto& socket = dynamic_cast<tlm::tlm_initiator_socket<>&>(*view.object);
    return socket->transport_dbg(transaction) == length;
  }

  // A dotted path as a single SystemC name: "io.ram" becomes "io_ram".
  static std::string FlatName(std::string path) {
    std::ranges::replace(path, '.', '_');
    return path;
  }

  // The signal a wire source drives, created the first time it is bound.
  // It is named after its driver: "reset_driver.line" drives
  // "reset_driver_line".
  sc_core::sc_signal<bool>& WireDrivenBy(const Port& source,
                                         const std::string& path) {
    auto& wire = wires_[source.object];
    if (!wire) {
      wire = std::make_unique<sc_core::sc_signal<bool>>(FlatName(path).c_str());
      dynamic_cast<sc_core::sc_out<bool>&>(*source.object).bind(*wire);
    }
    return *wire;
  }

  Group& GroupAt(const std::string& path) {
    auto& found = groups_[path];
    if (!found) {
      found = InsideParent(
          path, [](const char* name) { return std::make_unique<Group>(name); });
    }
    return *found;
  }

  Instance& InstanceAt(const std::string& path) {
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

  const Port& PortAt(const std::string& path) {
    const auto dot = path.rfind('.');
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

  Registry registry_;
  // Groups are declared before instances so they outlive the components
  // built inside them.
  std::map<std::string, std::unique_ptr<Group>> groups_;
  std::map<std::string, Instance> instances_;
  std::map<const sc_core::sc_object*, std::unique_ptr<sc_core::sc_signal<bool>>>
      wires_;
  std::vector<std::unique_ptr<sc_core::sc_module>> tie_offs_;
  std::set<const sc_core::sc_object*> bound_;
  Trace trace_;
  std::vector<std::unique_ptr<Tracer>> tracers_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_PLATFORM_H_
