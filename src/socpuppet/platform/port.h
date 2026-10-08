#ifndef SOCPUPPET_PLATFORM_PORT_H_
#define SOCPUPPET_PLATFORM_PORT_H_

#include <string>
#include <utility>
#include <variant>

#include <systemc>
#include <tlm>

namespace socpuppet {

// A named connection point on a component, so that a platform can be wired
// up by name at run time.
struct Port {
  enum class Kind {
    kBus,   // a memory-mapped TLM-2.0 socket
    kWire,  // a single boolean line, such as an interrupt or a reset
  };
  enum class Role {
    // Where the connection is driven from: a TLM initiator socket, or a
    // wire's driver.
    kSource,
    // Where it arrives: a TLM target socket, or a wire's reader.
    kSink,
  };

  // The four things a port can be, as SystemC and TLM know them. Which one
  // a port holds is what gives it its kind and its role.
  using Initiator = tlm::tlm_initiator_socket<>*;
  using Target = tlm::tlm_target_socket<>*;
  using WireSource = sc_core::sc_out<bool>*;
  using WireSink = sc_core::sc_in<bool>*;

  std::string name;
  std::variant<Initiator, Target, WireSource, WireSink> connector;
  // A required port must be bound before the simulation starts.
  bool required = true;
};

inline Port::Kind KindOf(const Port& port) {
  return std::holds_alternative<Port::Initiator>(port.connector) ||
                 std::holds_alternative<Port::Target>(port.connector)
             ? Port::Kind::kBus
             : Port::Kind::kWire;
}

inline Port::Role RoleOf(const Port& port) {
  return std::holds_alternative<Port::Initiator>(port.connector) ||
                 std::holds_alternative<Port::WireSource>(port.connector)
             ? Port::Role::kSource
             : Port::Role::kSink;
}

// The SystemC object behind a port, which is what tells one port from
// another.
inline const sc_core::sc_object* ObjectOf(const Port& port) {
  return std::visit(
      [](const auto* object) -> const sc_core::sc_object* { return object; },
      port.connector);
}

inline const char* ToString(Port::Kind kind) {
  return kind == Port::Kind::kBus ? "bus" : "wire";
}

// A bus port that is not required may be left unconnected. An access sent
// out of an unconnected initiator gets an address-error response.
inline Port InitiatorPort(std::string name, tlm::tlm_initiator_socket<>& socket,
                          bool required = true) {
  return {.name = std::move(name), .connector = &socket, .required = required};
}

inline Port TargetPort(std::string name, tlm::tlm_target_socket<>& socket,
                       bool required = true) {
  return {.name = std::move(name), .connector = &socket, .required = required};
}

// A wire output that is not required may be left unconnected. It then
// drives a wire that nobody reads.
inline Port WireSourcePort(std::string name, sc_core::sc_out<bool>& out,
                           bool required = true) {
  return {.name = std::move(name), .connector = &out, .required = required};
}

// A wire input may be left unconnected; the component then sees it as low.
inline Port WireSinkPort(std::string name, sc_core::sc_in<bool>& in) {
  return {.name = std::move(name), .connector = &in, .required = false};
}

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_PORT_H_
