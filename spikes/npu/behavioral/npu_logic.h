#ifndef SPIKES_NPU_BEHAVIORAL_NPU_LOGIC_H_
#define SPIKES_NPU_BEHAVIORAL_NPU_LOGIC_H_

#include <cstdint>
#include <span>
#include <vector>

#include "socpuppet/core/memory_port.h"
#include "spikes/npu/behavioral/multiplier.h"
#include "spikes/npu/doorbell.h"

namespace spike {

// 🎭 What the behavioral NPU does, with no simulator attached. Its
// registers are the doorbell's. When the bell is rung it reads the
// descriptor, reads A and B from memory, has its Multiplier make C, and
// writes C back. It fits socpuppet's CommandLogic concept
// (socpuppet/models/command_device.h), so the DMA engine's SystemC shell
// is its shell too.
class NpuLogic {
 public:
  NpuLogic(socpuppet::MemoryPort& memory, Multiplier& multiplier)
      : memory_(memory), multiplier_(multiplier) {}

  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const {
    return doorbell_.ReadRegister(offset, out);
  }
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in) {
    return doorbell_.WriteRegister(offset, in);
  }

  // Does what the bell was rung for, if it has not been done yet. Returns
  // whether there was anything to do.
  bool CarryOut() {
    if (doorbell_.Pending() == 0) return false;
    doorbell_.Complete(Do());
    return true;
  }

  bool Interrupting() const { return doorbell_.Interrupting(); }

 private:
  // The one job the NPU knows: a matrix multiply. Returns whether it could
  // be carried out.
  bool Do() {
    MatmulDescriptor job;
    if (!job.Load(memory_, doorbell_.Descriptor())) return false;
    // Sizes a model can hold: nothing in the descriptor says the host is
    // being reasonable.
    constexpr std::uint32_t kLargest = 4096;
    if (job.m == 0 || job.k == 0 || job.n == 0 || job.m > kLargest ||
        job.k > kLargest || job.n > kLargest) {
      return false;
    }
    std::vector<std::int8_t> a(std::size_t{job.m} * job.k);
    std::vector<std::int8_t> b(std::size_t{job.k} * job.n);
    std::vector<std::int32_t> c(std::size_t{job.m} * job.n);
    if (!memory_.Read(job.a, AsBytes(a)) || !memory_.Read(job.b, AsBytes(b))) {
      return false;
    }
    if (!multiplier_.Multiply(a, b, c, job.m, job.k, job.n)) return false;
    return memory_.Write(job.c, AsBytes(c));
  }

  template <typename T>
  static std::span<std::uint8_t> AsBytes(std::vector<T>& values) {
    // The machine running the simulation is little-endian, as the host is.
    return {reinterpret_cast<std::uint8_t*>(values.data()),
            values.size() * sizeof(T)};
  }

  socpuppet::MemoryPort& memory_;
  Multiplier& multiplier_;
  DoorbellLogic doorbell_;
};

}  // namespace spike

#endif  // SPIKES_NPU_BEHAVIORAL_NPU_LOGIC_H_
