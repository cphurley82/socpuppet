#ifndef SOCPUPPET_PLATFORM_TRANSPORT_H_
#define SOCPUPPET_PLATFORM_TRANSPORT_H_

#include <cstddef>
#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>

namespace socpuppet {

// Sets a payload up for the one kind of access everything here makes: a
// read or a write of a run of bytes at an address, with no byte enables
// and no streaming. The payload points at `data` until the access is done.
inline void SetUpAccess(tlm::tlm_generic_payload& transaction,
                        tlm::tlm_command command, std::uint64_t address,
                        std::span<std::uint8_t> data) {
  transaction.set_command(command);
  transaction.set_address(address);
  transaction.set_data_ptr(data.data());
  transaction.set_data_length(static_cast<unsigned>(data.size()));
  transaction.set_streaming_width(static_cast<unsigned>(data.size()));
}

// The bytes a write carries, as a payload wants them. A payload's pointer
// is not const, but TLM forbids a target to change the data of a write, so
// the bytes are safe.
inline std::span<std::uint8_t> WriteData(std::span<const std::uint8_t> data) {
  return {const_cast<std::uint8_t*>(data.data()), data.size()};
}

// A blocking access through an initiator socket: sets a payload up, sends
// it and returns the target's response. `delay` goes in as how far ahead of
// the simulation's clock the initiator is running, and comes back with
// however long the target said the access took added on.
template <typename Socket>
tlm::tlm_response_status Transport(Socket& socket, tlm::tlm_command command,
                                   std::uint64_t address,
                                   std::span<std::uint8_t> data,
                                   sc_core::sc_time& delay) {
  tlm::tlm_generic_payload transaction;
  SetUpAccess(transaction, command, address, data);
  socket->b_transport(transaction, delay);
  return transaction.get_response_status();
}

// The same, by an initiator that runs on the simulation's clock: it has no
// lead to stamp the access with and nothing to learn from the delay.
template <typename Socket>
tlm::tlm_response_status Transport(Socket& socket, tlm::tlm_command command,
                                   std::uint64_t address,
                                   std::span<std::uint8_t> data) {
  sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
  return Transport(socket, command, address, data, delay);
}

// A debug access through an initiator socket: the same access with no
// simulated time and no side effects, the way a debugger looks at memory.
// Returns how many bytes the target transferred, which is fewer than asked
// for when it declined.
template <typename Socket>
unsigned DebugTransport(Socket& socket, tlm::tlm_command command,
                        std::uint64_t address, std::span<std::uint8_t> data) {
  tlm::tlm_generic_payload transaction;
  SetUpAccess(transaction, command, address, data);
  return socket->transport_dbg(transaction);
}

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_TRANSPORT_H_
