#ifndef SOCPUPPET_PLATFORM_SLOTS_H_
#define SOCPUPPET_PLATFORM_SLOTS_H_

#include <concepts>
#include <cstddef>
#include <string>

#include <systemc>
#include <tlm>

namespace socpuppet {

// Slot contracts, as C++20 concepts.
//
// A slot is a place in a platform that different implementations can fill:
// a stand-in today, the full model later. A concept states the shape an
// implementation must have to fit the slot. The contract test suites in
// tests/cpp/contracts state how it must behave, and are constrained by
// these concepts, so a type that does not fit fails to compile with a
// message naming the slot.

// A memory: built from a name and a size in bytes, reached through one TLM
// target socket.
template <typename T>
concept MemorySlot =
    std::constructible_from<T, sc_core::sc_module_name, std::size_t> &&
    requires(T memory) {
      { memory.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
    };

// One end of a die-to-die link: built from a name, with a die-facing pair
// of sockets and a peer-facing pair.
template <typename T>
concept LinkEndpointSlot =
    std::constructible_from<T, sc_core::sc_module_name> &&
    requires(T endpoint) {
      { endpoint.target } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      {
        endpoint.initiator
      } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
      {
        endpoint.peer_target
      } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      {
        endpoint.peer_initiator
      } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
    };

// A UART: built from a name, reached through one TLM target socket, and
// keeping what was transmitted through it as text.
template <typename T>
concept UartSlot =
    std::constructible_from<T, sc_core::sc_module_name> && requires(T uart) {
      { uart.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { uart.Output() } -> std::convertible_to<std::string>;
    };

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_SLOTS_H_
