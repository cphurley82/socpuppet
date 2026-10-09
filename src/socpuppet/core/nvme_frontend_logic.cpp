#include "socpuppet/core/nvme_frontend_logic.h"

namespace socpuppet {

namespace {

// How long the host is told to wait for the controller to become ready, in
// units of 500 ms: a second, which is long enough for firmware to start.
constexpr std::uint8_t kReadyTimeout = 2;

}  // namespace

NvmeFrontendLogic::NvmeFrontendLogic(MemoryPort& host_memory,
                                     std::size_t /*vectors*/)
    : queues_(host_memory) {}

bool NvmeFrontendLogic::ReadHostRegister(std::uint64_t offset,
                                         std::span<std::uint8_t> out) const {
  return host_registers_.Read(offset, out, {.ready_timeout = kReadyTimeout});
}

}  // namespace socpuppet
