#ifndef SOCPUPPET_PLATFORM_PLATFORM_H_
#define SOCPUPPET_PLATFORM_PLATFORM_H_

#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <span>
#include <stdexcept>
#include <string>
#include <typeinfo>
#include <vector>

#include <systemc>
#include <tlm>

#include "socpuppet/core/trace.h"
#include "socpuppet/platform/port.h"
#include "socpuppet/platform/registry.h"
#include "socpuppet/platform/tracer.h"

namespace socpuppet {

// A platform under construction: components created by implementation name
// and wired together by port name.
//
// Names are dotted paths. In "io.ram", "io" is a group (a die, say) and
// "ram" is the component inside it; the same path names the component in
// the simulation, in traces and in error messages.
//
// It is built in two steps. Add() and Bind() describe it, and Elaborate()
// fixes it: after that it can be run and looked into, and no longer
// changed. Each call says so if it comes at the wrong time.
class Platform {
 public:
  explicit Platform(Registry registry);
  ~Platform();

  void Add(const std::string& path, const std::string& implementation,
           const Config& config = {});

  // Binds two ports, each named "<component path>.<port>". The first must
  // be a source (a TLM initiator socket, or a wire's driver) and the second
  // a sink (a TLM target socket, or a wire's reader), both of one kind.
  //
  // A traced bus connection gets a Tracer in the middle, which records every
  // transaction that crosses it (see RecordedTrace()).
  void Bind(const std::string& source, const std::string& sink,
            bool traced = false);

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
  void SetQuantum(const sc_core::sc_time& quantum);

  // Finishes construction: checks the wiring, then has SystemC complete its
  // elaboration (resolving every binding) and get ready to simulate, without
  // running any process yet. After this, debug accesses work and the
  // topology is fixed.
  void Elaborate();

  // Runs until nothing is left to do. Throws if a model stopped the
  // simulation with an error (see failure.h).
  void Run();

  // Runs for `duration` of simulated time.
  void Run(const sc_core::sc_time& duration);

  // Moves to the next moment at which anything is scheduled and lets
  // everything scheduled for that moment happen. Returns false, having done
  // nothing more than finish the current moment, if nothing further is
  // scheduled.
  bool Step();

  // How far away the next scheduled activity is, once everything scheduled
  // for the current moment has happened. Nothing, if nothing is scheduled.
  std::optional<sc_core::sc_time> TimeToNextActivity();

  // Everything recorded on traced connections so far.
  const Trace& RecordedTrace() const { return trace_; }

  // The current simulated time.
  sc_core::sc_time Time() const;

  // Debug accesses as seen from an initiator port: no simulated time passes
  // and nothing in the platform notices, the way a debugger reads memory.
  // Each returns false if nothing at that address took the access.
  bool DebugRead(const std::string& via, std::uint64_t address,
                 std::span<std::byte> data);
  bool DebugWrite(const std::string& via, std::uint64_t address,
                  std::span<const std::byte> data);

  // The ports of the component at `path`.
  const std::vector<Port>& Ports(const std::string& path);

  // The component at `path`, as its concrete C++ type. An escape hatch for
  // C++ callers that need more than composing by name offers.
  template <typename Module>
  Module& ModuleAt(const std::string& path) {
    sc_core::sc_module& module = *InstanceAt(path).module;
    if (auto* wanted = dynamic_cast<Module*>(&module)) return *wanted;
    throw NotOfThatType(path, typeid(module), typeid(Module));
  }

 private:
  // A wire: one boolean line, with one driver. A device whose line can
  // change for more than one reason (it is written to, say, and its own
  // timer runs out) drives it from one process of its own even so, as
  // hardware has one driver per wire. SystemC checks at the first write
  // from a second process, and names the wire and both of them.
  using Wire = sc_core::sc_signal<bool, sc_core::SC_ONE_WRITER>;

  // A level of naming with no behavior of its own.
  struct Group;

  // Each refuses a call that comes at the wrong time, saying what was
  // attempted.
  void RefuseOnceElaborated(const char* attempt) const;
  void RefuseUnlessElaborated(const char* attempt) const;

  void BindBus(tlm::tlm_initiator_socket<>& initiator,
               tlm::tlm_target_socket<>& target, const std::string& source,
               const std::string& sink, bool traced);
  void TieOffUnconnectedPorts();
  // Runs delta cycles until nothing more is scheduled for the current time.
  void FinishThisMoment();
  // SystemC would also object to an unbound port, but only once the
  // simulation starts and in its own terms.
  void CheckWiring() const;
  bool Debug(tlm::tlm_command command, const std::string& via,
             std::uint64_t address, std::span<std::uint8_t> data);

  // The signal a wire source drives, created the first time it is bound.
  // It is named after its driver: "reset_driver.line" drives
  // "reset_driver_line".
  Wire& WireDrivenBy(sc_core::sc_out<bool>& source, const std::string& path);

  // Calls make(leaf name) inside the group that `path` puts it in, so that
  // SystemC names the new module by its full path.
  template <typename Make>
  auto InsideParent(const std::string& path, Make make) -> decltype(make(""));
  Group& GroupAt(const std::string& path);
  Instance& InstanceAt(const std::string& path);
  const Port& PortAt(const std::string& path);
  static std::invalid_argument NotOfThatType(const std::string& path,
                                             const std::type_info& is,
                                             const std::type_info& wanted);

  Registry registry_;
  bool elaborated_ = false;
  // Groups are declared before instances so they outlive the components
  // built inside them.
  std::map<std::string, std::unique_ptr<Group>> groups_;
  std::map<std::string, Instance> instances_;
  std::map<const sc_core::sc_object*, std::unique_ptr<Wire>> wires_;
  std::vector<std::unique_ptr<sc_core::sc_module>> tie_offs_;
  std::set<const sc_core::sc_object*> bound_;
  Trace trace_;
  std::vector<std::unique_ptr<Tracer>> tracers_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_PLATFORM_H_
