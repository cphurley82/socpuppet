#ifndef SOCPUPPET_PLATFORM_SLOTS_H_
#define SOCPUPPET_PLATFORM_SLOTS_H_

#include <concepts>
#include <cstddef>
#include <cstdint>
#include <string>

#include <systemc>
#include <tlm>

namespace socpuppet {

// Slot contracts, as C++20 concepts.
//
// A slot is a place in a platform that different implementations can fill:
// a stand-in today, the full model later. A concept states the shape an
// implementation must have to fit the slot. The contract test suites in
// tests/cpp/contracts state how it must behave. Most are constrained by
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

// A CPU, or whatever stands in for one: something that starts bus accesses
// through one TLM initiator socket, and has inputs for the external
// interrupt, the timer interrupt and reset. How it is built is its own
// business: a CPU model needs to know its word size, a scripted stand-in does
// not. How it must behave is the bus-master contract
// (tests/cpp/contracts/bus_master_contract.h).
template <typename T>
concept CpuSlot = requires(T cpu) {
  { cpu.socket } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
  { cpu.irq } -> std::convertible_to<sc_core::sc_in<bool>&>;
  { cpu.timer_irq } -> std::convertible_to<sc_core::sc_in<bool>&>;
  { cpu.reset } -> std::convertible_to<sc_core::sc_in<bool>&>;
};

// A RISC-V machine timer: built from a name and how many times a second it
// counts, reached through one TLM target socket, with one interrupt output.
template <typename T>
concept MachineTimerSlot =
    std::constructible_from<T, sc_core::sc_module_name, std::uint64_t> &&
    requires(T timer) {
      { timer.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { timer.irq } -> std::convertible_to<sc_core::sc_out<bool>&>;
    };

// An interrupt controller: built from a name, reached through one TLM
// target socket, with a vector of interrupt inputs called `sources` and
// one interrupt output for the CPU.
template <typename T>
concept InterruptControllerSlot =
    std::constructible_from<T, sc_core::sc_module_name> &&
    requires(T controller) {
      { controller.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      {
        controller.sources
      } -> std::convertible_to<sc_core::sc_vector<sc_core::sc_in<bool>>&>;
      { controller.irq } -> std::convertible_to<sc_core::sc_out<bool>&>;
    };

// A UART: built from a name, reached through one TLM target socket, and
// keeping what was transmitted through it as text.
template <typename T>
concept UartSlot =
    std::constructible_from<T, sc_core::sc_module_name> && requires(T uart) {
      { uart.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { uart.Output() } -> std::convertible_to<std::string>;
    };

// An NVMe function: an NVMe controller as the PCIe endpoint around it sees
// it, with no PCIe of its own. It has a register block to be put behind
// the endpoint's first base address register (`bar0`), a port for reading
// and writing the host's memory (`dma`), and one interrupt line per
// vector. How it is built is its own business, and it need not be one
// component: the full SSD will be several. So the NVMe contract
// (tests/cpp/contracts/nvme_contract.h), which says how it must behave,
// finds these three by port name, and this concept is for a function that
// is one component.
template <typename T>
concept NvmeFunctionSlot = requires(T function) {
  { function.bar0 } -> std::convertible_to<tlm::tlm_target_socket<>&>;
  { function.dma } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
  {
    function.irq
  } -> std::convertible_to<sc_core::sc_vector<sc_core::sc_out<bool>>&>;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_SLOTS_H_
