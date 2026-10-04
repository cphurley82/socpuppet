#ifndef SOCPUPPET_PLATFORM_PORT_H_
#define SOCPUPPET_PLATFORM_PORT_H_

#include <string>
#include <utility>

#include <systemc>
#include <tlm>

namespace socpuppet {

// A named connection point on a component, with its concrete type erased so
// that a platform can be wired up by name at run time.
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

  std::string name;
  Kind kind;
  Role role;
  sc_core::sc_object* object;
  // A required port must be bound before the simulation starts.
  bool required = true;
};

inline const char* ToString(Port::Kind kind) {
  return kind == Port::Kind::kBus ? "bus" : "wire";
}

// A bus port that is not required may be left unconnected. An access sent
// out of an unconnected initiator gets an address-error response.
inline Port InitiatorPort(std::string name, tlm::tlm_initiator_socket<>& socket,
                          bool required = true) {
  return {.name = std::move(name),
          .kind = Port::Kind::kBus,
          .role = Port::Role::kSource,
          .object = &socket,
          .required = required};
}

inline Port TargetPort(std::string name, tlm::tlm_target_socket<>& socket,
                       bool required = true) {
  return {.name = std::move(name),
          .kind = Port::Kind::kBus,
          .role = Port::Role::kSink,
          .object = &socket,
          .required = required};
}

inline Port WireSourcePort(std::string name, sc_core::sc_out<bool>& out) {
  return {.name = std::move(name),
          .kind = Port::Kind::kWire,
          .role = Port::Role::kSource,
          .object = &out};
}

// A wire input may be left unconnected; the component then sees it as low.
inline Port WireSinkPort(std::string name, sc_core::sc_in<bool>& in) {
  return {.name = std::move(name),
          .kind = Port::Kind::kWire,
          .role = Port::Role::kSink,
          .object = &in,
          .required = false};
}

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_PORT_H_
