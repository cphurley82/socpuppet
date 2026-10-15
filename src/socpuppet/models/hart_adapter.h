#ifndef SOCPUPPET_MODELS_HART_ADAPTER_H_
#define SOCPUPPET_MODELS_HART_ADAPTER_H_

#include <array>
#include <cstdint>
#include <optional>

#include <systemc>
#include <tlm>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/hart_registers.h"
#include "socpuppet/platform/transport.h"

// What the adapters around a borrowed CPU (dbt_rise_cpu.cpp, qbox_cpu.cpp)
// do alike, to fit it to a socpuppet platform.
namespace socpuppet {

// The machine timer's count at the time a CPU `lead` ahead of the clock
// has got to, read through the CPU's `time` socket, or zero if there is no
// timer at the other end. What a CPU's `time` register reads.
template <typename Socket>
std::uint64_t ReadTheTimer(Socket& time, sc_core::sc_time lead) {
  std::array<std::uint8_t, 8> count{};
  const tlm::tlm_response_status response =
      Transport(time, tlm::TLM_READ_COMMAND, 0, count, lead);
  return response == tlm::TLM_OK_RESPONSE
             ? LoadLittleEndian<std::uint64_t>(count)
             : 0;
}

// Lets a change a CPU's own access made to an interrupt line reach the
// CPU before it executes another instruction. A handler's write to its
// device, or a claim at an IMSIC, is what quiets an interrupt. The CPU
// hears of a line from a method, which cannot run until the CPU's thread
// yields, and with a quantum that is a thousand instructions off. Without
// this the CPU would return from its handler still seeing the interrupt
// pending, and take it again and again. One delta cycle runs the device's
// method and updates its line, a second runs the adapter's. DBT-RISE's
// core is patched to do the same after its bus accesses
// (interrupt-after-access).
inline void LetALineThatChangedBeHeard() {
  for (int delta = 0;
       delta < 2 && sc_core::sc_pending_activity_at_current_time(); ++delta) {
    sc_core::wait(sc_core::SC_ZERO_TIME);
  }
}

// A read of a register that another block keeps for a hart, at `address`
// (models/hart_registers.h), through the hart's `csr` socket, or nothing
// if the block has no such register. `lead` means nothing to whoever
// answers. It is the CPU's all the same, so that a trace of the socket has
// the access where the bus accesses around it are.
template <typename Socket>
std::optional<std::uint64_t> ReadHartRegister(Socket& csr,
                                              std::uint64_t address,
                                              sc_core::sc_time lead) {
  std::array<std::uint8_t, kHartRegisterBytes> bytes{};
  if (Transport(csr, tlm::TLM_READ_COMMAND, address, bytes, lead) !=
      tlm::TLM_OK_RESPONSE) {
    return std::nullopt;
  }
  return LoadLittleEndian<std::uint64_t>(bytes);
}

// A write of one, after which a line the write changed is heard: a claim
// is what quiets an IMSIC's. Returns whether the block had such a register.
template <typename Socket>
bool WriteHartRegister(Socket& csr, std::uint64_t address, std::uint64_t value,
                       sc_core::sc_time lead) {
  auto bytes = LittleEndianBytes(value);
  if (Transport(csr, tlm::TLM_WRITE_COMMAND, address, bytes, lead) !=
      tlm::TLM_OK_RESPONSE) {
    return false;
  }
  LetALineThatChangedBeHeard();
  return true;
}

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_HART_ADAPTER_H_
