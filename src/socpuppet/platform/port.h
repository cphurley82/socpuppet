#pragma once

#include <string>
#include <utility>

#include <systemc>
#include <tlm>

namespace socpuppet {

// A named connection point on a component, with its concrete type erased so
// that a platform can be wired up by name at run time.
struct Port {
  enum class Kind {
    bus,   // a memory-mapped TLM-2.0 socket
    wire,  // a single boolean line, such as an interrupt or a reset
  };
  enum class Role {
    source,  // where the connection is driven from: a TLM initiator socket, a wire's driver
    sink,    // where it arrives: a TLM target socket, a wire's reader
  };

  std::string name;
  Kind kind;
  Role role;
  sc_core::sc_object* object;
  // A required port must be bound before the simulation starts.
  bool required = true;
};

inline const char* to_string(Port::Kind kind) { return kind == Port::Kind::bus ? "bus" : "wire"; }

inline Port initiator_port(std::string name, tlm::tlm_initiator_socket<>& socket) {
  return {std::move(name), Port::Kind::bus, Port::Role::source, &socket};
}

inline Port target_port(std::string name, tlm::tlm_target_socket<>& socket) {
  return {std::move(name), Port::Kind::bus, Port::Role::sink, &socket};
}

inline Port wire_source_port(std::string name, sc_core::sc_out<bool>& out) {
  return {std::move(name), Port::Kind::wire, Port::Role::source, &out};
}

// A wire input may be left unconnected; the component then sees it as low.
inline Port wire_sink_port(std::string name, sc_core::sc_in<bool>& in) {
  return {std::move(name), Port::Kind::wire, Port::Role::sink, &in, /*required=*/false};
}

}  // namespace socpuppet
