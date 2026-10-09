#ifndef SOCPUPPET_CORE_DMA_ENGINE_LOGIC_H_
#define SOCPUPPET_CORE_DMA_ENGINE_LOGIC_H_

#include <cstdint>
#include <optional>
#include <span>

#include "socpuppet/core/command_status.h"
#include "socpuppet/core/memory_port.h"

namespace socpuppet {

// What an SSD's DMA engine does, with no simulator attached: the registers
// the SSD's CPU talks to, and the bytes it copies between the host's
// memory and the SSD's own when told to.
class DmaEngineLogic {
 public:
  DmaEngineLogic(MemoryPort& host_memory, MemoryPort& local_memory);

  // Reads and writes of the register block, by the CPU. Each returns false,
  // and touches nothing, if the access is refused.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const;
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in);

  // Does what the command register was last told, if it has not been done
  // yet. Returns whether there was anything to do.
  bool CarryOut();

 private:
  // A command, with what the registers said it was about when it was given.
  struct Job {
    std::uint32_t command;
    std::uint64_t host_address;
    std::uint32_t local_address;
    std::uint32_t length;
  };

  // Carries a command out, and returns whether it could be.
  bool Do(const Job& job);

  MemoryPort& host_memory_;
  MemoryPort& local_memory_;
  // What the command register was told and has not done yet.
  std::optional<Job> job_;
  CommandStatus status_;
  // What to copy: where it is in the host's memory, where in the SSD's
  // own, and how many bytes.
  std::uint64_t host_address_ = 0;
  std::uint32_t local_address_ = 0;
  std::uint32_t length_ = 0;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_DMA_ENGINE_LOGIC_H_
