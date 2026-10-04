#pragma once

#include <string>
#include <utility>

#include <systemc>
#include <tlm>

namespace socpuppet {

// A named connection point on a component, with its concrete type erased so
// that a platform can be wired up by name at run time.
struct Port {
  enum class Role {
    source,  // starts the conversation: a TLM initiator socket
    sink,    // answers: a TLM target socket
  };

  std::string name;
  Role role;
  sc_core::sc_object* socket;
};

inline Port initiator_port(std::string name, tlm::tlm_initiator_socket<>& socket) {
  return {std::move(name), Port::Role::source, &socket};
}

inline Port target_port(std::string name, tlm::tlm_target_socket<>& socket) {
  return {std::move(name), Port::Role::sink, &socket};
}

}  // namespace socpuppet
