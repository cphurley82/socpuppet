#ifndef SOCPUPPET_MODELS_SOCKET_MEMORY_H_
#define SOCPUPPET_MODELS_SOCKET_MEMORY_H_

#include <cstdint>
#include <span>

#include <tlm>

#include "socpuppet/core/memory_port.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

// The memory behind one of a model's initiator sockets, as the model's
// logic reaches it: each read and write is one blocking access through the
// socket, and is taken if the response is OK. A model has one of these as
// a member for each socket its logic does DMA through.
template <typename Socket>
class SocketMemory final : public MemoryPort {
 public:
  explicit SocketMemory(Socket& socket) : socket_(socket) {}

  bool Read(std::uint64_t address, std::span<std::uint8_t> out) override {
    return Transport(socket_, tlm::TLM_READ_COMMAND, address, out) ==
           tlm::TLM_OK_RESPONSE;
  }
  bool Write(std::uint64_t address, std::span<const std::uint8_t> in) override {
    return Transport(socket_, tlm::TLM_WRITE_COMMAND, address, WriteData(in)) ==
           tlm::TLM_OK_RESPONSE;
  }

 private:
  Socket& socket_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_SOCKET_MEMORY_H_
