#ifndef SPIKES_NPU_DOORBELL_H_
#define SPIKES_NPU_DOORBELL_H_

#include <algorithm>
#include <array>
#include <cstdint>
#include <span>

#include "socpuppet/core/command_status.h"
#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/memory_port.h"

// The one block of ours that both of the spike's candidates share: a
// doorbell. The host describes the work in memory, writes where the
// description is, and rings the bell (writes the command register). When
// the work is done the host's interrupt line rises.
//
// It has two faces. The host's is a command device's register block
// (regs/command_device.rdl), with the descriptor's address after the
// three usual registers. The accelerator's is two registers more, which
// the host never touches: PENDING, which says what was asked for, and
// COMPLETE, which the accelerator writes when it is done. A behavioral
// accelerator has no need of the second face, since its work is done
// in-process, but a programmable core like Hexagon does: it has an
// interrupt controller for what comes in and nothing that raises a line
// on somebody else, so something has to turn its "done" into the host's
// interrupt.
//
// In the main tree this would be regs/npu_doorbell.rdl. A spike's register
// map lives here.
namespace spike {

// The host's face.
inline constexpr std::uint64_t kDoorbellCommand = 0x00;
inline constexpr std::uint64_t kDoorbellStatus = 0x04;
inline constexpr std::uint64_t kDoorbellInterruptEnable = 0x08;
inline constexpr std::uint64_t kDoorbellDescriptorLow = 0x0C;
inline constexpr std::uint64_t kDoorbellDescriptorHigh = 0x10;
// The accelerator's face.
inline constexpr std::uint64_t kDoorbellPending = 0x14;
inline constexpr std::uint64_t kDoorbellComplete = 0x18;
inline constexpr std::uint64_t kDoorbellBlockSize = 0x20;

// What the command register can be told.
inline constexpr std::uint32_t kDoorbellCommandMatmul = 1;
// What the accelerator writes to COMPLETE.
inline constexpr std::uint32_t kDoorbellCompleteDone = 1;
inline constexpr std::uint32_t kDoorbellCompleteError = 2;

// The status bits are a command device's.
inline constexpr std::uint32_t kDoorbellStatusDone = COMMAND_DEVICE_STATUS_DONE;
inline constexpr std::uint32_t kDoorbellStatusError =
    COMMAND_DEVICE_STATUS_ERROR;
inline constexpr std::uint32_t kDoorbellStatusBusy = COMMAND_DEVICE_STATUS_BUSY;

// The work, as it is described in memory: C = A x B, where A is m by k
// and B is k by n, both of 8-bit signed integers, row-major, and C is m by
// n of 32-bit signed integers. 40 bytes, little-endian.
struct MatmulDescriptor {
  std::uint64_t a = 0;
  std::uint64_t b = 0;
  std::uint64_t c = 0;
  std::uint32_t m = 0;
  std::uint32_t k = 0;
  std::uint32_t n = 0;
  std::uint32_t reserved = 0;

  static constexpr std::size_t kSize = 40;

  std::array<std::uint8_t, kSize> Bytes() const {
    std::array<std::uint8_t, kSize> bytes{};
    Put(bytes, 0, a);
    Put(bytes, 8, b);
    Put(bytes, 16, c);
    Put(bytes, 24, m);
    Put(bytes, 28, k);
    Put(bytes, 32, n);
    Put(bytes, 36, reserved);
    return bytes;
  }

  // Reads one from `memory` at `address`. Returns false if it could not.
  bool Load(socpuppet::MemoryPort& memory, std::uint64_t address) {
    std::array<std::uint8_t, kSize> bytes{};
    if (!memory.Read(address, bytes)) return false;
    a = Get<std::uint64_t>(bytes, 0);
    b = Get<std::uint64_t>(bytes, 8);
    c = Get<std::uint64_t>(bytes, 16);
    m = Get<std::uint32_t>(bytes, 24);
    k = Get<std::uint32_t>(bytes, 28);
    n = Get<std::uint32_t>(bytes, 32);
    reserved = Get<std::uint32_t>(bytes, 36);
    return true;
  }

 private:
  template <typename T>
  static void Put(std::span<std::uint8_t> bytes, std::size_t at, T value) {
    const auto little = socpuppet::LittleEndianBytes(value);
    std::copy(little.begin(), little.end(), bytes.subspan(at).begin());
  }
  template <typename T>
  static T Get(std::span<const std::uint8_t> bytes, std::size_t at) {
    return socpuppet::LoadLittleEndian<T>(bytes.subspan(at, sizeof(T)));
  }
};

// The doorbell's registers, with no simulator attached. The host's reads
// and writes come through ReadRegister and WriteRegister, as a command
// device's do. The accelerator's side is the two methods after them, which
// a programmable core reaches through its own face of the register block
// and an in-process one calls directly.
class DoorbellLogic {
 public:
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out) const {
    if (out.size() != 4) return false;
    std::uint32_t value = 0;
    switch (offset) {
      case kDoorbellCommand:
        break;
      case kDoorbellStatus:
        value = status_.Status();
        break;
      case kDoorbellInterruptEnable:
        value = status_.InterruptEnable();
        break;
      case kDoorbellDescriptorLow:
        value = static_cast<std::uint32_t>(descriptor_);
        break;
      case kDoorbellDescriptorHigh:
        value = static_cast<std::uint32_t>(descriptor_ >> 32);
        break;
      case kDoorbellPending:
        value = Pending();
        break;
      case kDoorbellComplete:
        break;
      default:
        return false;
    }
    const auto bytes = socpuppet::LittleEndianBytes(value);
    std::copy(bytes.begin(), bytes.end(), out.begin());
    return true;
  }

  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in) {
    if (in.size() != 4) return false;
    const auto value = socpuppet::LoadLittleEndian<std::uint32_t>(in);
    switch (offset) {
      case kDoorbellCommand:
        // A bell that is already ringing is not rung again.
        if (status_.Busy() || value != kDoorbellCommandMatmul) return true;
        status_.Start();
        pending_ = value;
        return true;
      case kDoorbellStatus:
        status_.WriteStatus(value);
        return true;
      case kDoorbellInterruptEnable:
        status_.WriteInterruptEnable(value);
        return true;
      case kDoorbellDescriptorLow:
        descriptor_ = (descriptor_ & ~std::uint64_t{0xFFFF'FFFF}) | value;
        return true;
      case kDoorbellDescriptorHigh:
        descriptor_ =
            (descriptor_ & 0xFFFF'FFFF) | (std::uint64_t{value} << 32);
        return true;
      case kDoorbellPending:
        return true;
      case kDoorbellComplete:
        if (Pending() != 0) Complete(value == kDoorbellCompleteDone);
        return true;
      default:
        return false;
    }
  }

  // The accelerator's side. Pending() is the command the host gave and
  // nobody has completed yet, or zero. Descriptor() is where the host said
  // the work is described. Complete() is the accelerator saying it is done,
  // and how it went.
  std::uint32_t Pending() const { return pending_; }
  std::uint64_t Descriptor() const { return descriptor_; }
  void Complete(bool carried_out) {
    pending_ = 0;
    status_.Finish(carried_out);
  }

  bool Interrupting() const { return status_.Interrupting(); }

 private:
  socpuppet::CommandStatus status_;
  std::uint64_t descriptor_ = 0;
  std::uint32_t pending_ = 0;
};

}  // namespace spike

#endif  // SPIKES_NPU_DOORBELL_H_
