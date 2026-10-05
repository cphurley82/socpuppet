#ifndef SPIKES_ISS_QBOX_CPU_SLOT_H_
#define SPIKES_ISS_QBOX_CPU_SLOT_H_

#include <concepts>

#include <systemc>
#include <tlm>

namespace spike {

// A draft of the CPU slot, for the ISS spike (milestone M1) only.
//
// A CPU is whatever fills this shape: one bus socket it sends its reads
// and writes out of, an interrupt input and a reset input. That is the
// shape the scripted bus master already has, so a real CPU model can take
// the stand-in's place without its neighbors changing.
//
// What the spike expects of a candidate beyond the shape:
//   reset  While it is high the CPU executes nothing. Releasing it starts
//          execution at the reset address, and raising it again restarts.
//   DMI    The CPU asks for direct memory access once a transaction comes
//          back with the DMI-allowed hint, and stops using a pointer when
//          it is invalidated.
//   time   The CPU runs ahead of the kernel by at most the global quantum
//          and passes how far ahead it is as the delay of each
//          transaction.
//
// The real contract is M3's to write, in src/socpuppet/platform/slots.h.
template <typename T>
concept CpuSlot = std::derived_from<T, sc_core::sc_module> && requires(T cpu) {
  { cpu.socket } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
  { cpu.irq } -> std::convertible_to<sc_core::sc_in<bool>&>;
  { cpu.reset } -> std::convertible_to<sc_core::sc_in<bool>&>;
};

}  // namespace spike

#endif  // SPIKES_ISS_QBOX_CPU_SLOT_H_
