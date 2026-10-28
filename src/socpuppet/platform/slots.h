#ifndef SOCPUPPET_PLATFORM_SLOTS_H_
#define SOCPUPPET_PLATFORM_SLOTS_H_

#include <concepts>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

#include <systemc>
#include <tlm>

#include "socpuppet/core/nand_geometry.h"
#include "socpuppet/core/spi_device.h"

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

// One end of a die-to-die link: a die-facing pair of sockets and a
// peer-facing pair. How it is built is its own business, as a CPU's is: the
// pass-through needs only a name, and a link with timing and training needs
// to be told about both.
template <typename T>
concept LinkEndpointSlot = requires(T endpoint) {
  { endpoint.target } -> std::convertible_to<tlm::tlm_target_socket<>&>;
  { endpoint.initiator } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
  { endpoint.peer_target } -> std::convertible_to<tlm::tlm_target_socket<>&>;
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
// counts, with its registers reached through one TLM target socket, and
// with one interrupt output. A second target socket, `time`, is where a
// hart reads the count from with no bus in between: RISC-V's `time`
// register.
template <typename T>
concept MachineTimerSlot =
    std::constructible_from<T, sc_core::sc_module_name, std::uint64_t> &&
    requires(T timer) {
      { timer.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { timer.time } -> std::convertible_to<tlm::tlm_target_socket<>&>;
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

// An interrupt controller that is sent messages, where the one above has
// lines: RISC-V's IMSIC. It is built from a name and the highest interrupt
// identity it has, and keeps an interrupt file for machine mode and one
// for supervisor mode. Each file has a target socket for the page a device
// writes its message to, and an interrupt output for the hart. The hart
// reaches the files' registers through a third target socket, `csr`, as
// socpuppet/models/hart_registers.h has it.
template <typename T>
concept MessageControllerSlot =
    std::constructible_from<T, sc_core::sc_module_name, std::uint32_t> &&
    requires(T controller) {
      { controller.machine } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      {
        controller.supervisor
      } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { controller.csr } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { controller.irq } -> std::convertible_to<sc_core::sc_out<bool>&>;
      {
        controller.supervisor_irq
      } -> std::convertible_to<sc_core::sc_out<bool>&>;
    };

// An interrupt controller that takes devices' lines and sends messages:
// RISC-V's APLIC, delivering by message. It is built from a name, reached
// through one TLM target socket, and has a vector of interrupt inputs
// called `sources` and an initiator socket its messages go out of, each a
// write to the page of a hart's message controller.
template <typename T>
concept AplicSlot =
    std::constructible_from<T, sc_core::sc_module_name> && requires(T aplic) {
      { aplic.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      {
        aplic.sources
      } -> std::convertible_to<sc_core::sc_vector<sc_core::sc_in<bool>>&>;
      { aplic.msi } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
    };

// An IOMMU: what stands between devices and memory. It is built from a
// name. Its registers are reached through one TLM target socket, `socket`;
// devices' accesses come in at `target` and go out at `initiator`, with the
// IOMMU's own reads and writes of memory; `irq` is its interrupt.
template <typename T>
concept IommuSlot =
    std::constructible_from<T, sc_core::sc_module_name> && requires(T iommu) {
      { iommu.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { iommu.target } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { iommu.initiator } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
      { iommu.irq } -> std::convertible_to<sc_core::sc_out<bool>&>;
    };

// A watchdog timer: built from a name, with its registers reached through
// one TLM target socket. It has two outputs. `irq` is its interrupt, for an
// interrupt controller's input, and `bite` is the line that rises when
// firmware has let it run out, for whatever resets the CPU.
template <typename T>
concept WatchdogSlot = std::constructible_from<T, sc_core::sc_module_name> &&
                       requires(T watchdog) {
                         {
                           watchdog.socket
                         } -> std::convertible_to<tlm::tlm_target_socket<>&>;
                         {
                           watchdog.irq
                         } -> std::convertible_to<sc_core::sc_out<bool>&>;
                         {
                           watchdog.bite
                         } -> std::convertible_to<sc_core::sc_out<bool>&>;
                       };

// An SPI controller: built from a name and its clock in hertz, and reached
// through one TLM target socket, with one interrupt output. The devices on
// its bus are attached by chip select, each a SpiDevice that the
// controller talks to a byte at a time.
template <typename T>
concept SpiControllerSlot =
    std::constructible_from<T, sc_core::sc_module_name, std::uint64_t> &&
    requires(T controller, unsigned chip_select, SpiDevice& device) {
      { controller.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { controller.irq } -> std::convertible_to<sc_core::sc_out<bool>&>;
      controller.Attach(chip_select, device);
    };

// A UART: built from a name and reached through one TLM target socket.
// Whoever is at the other end of its serial line is the test or the script
// that holds it: what the UART transmitted is kept as text, and bytes are
// handed to it to receive, which show in its registers a delta cycle on.
// It has one interrupt output, for an interrupt controller's input.
template <typename T>
concept UartSlot = std::constructible_from<T, sc_core::sc_module_name> &&
                   requires(T uart, std::string_view received) {
                     {
                       uart.socket
                     } -> std::convertible_to<tlm::tlm_target_socket<>&>;
                     {
                       uart.irq
                     } -> std::convertible_to<sc_core::sc_out<bool>&>;
                     { uart.Output() } -> std::convertible_to<std::string>;
                     uart.Write(received);
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

// A NAND flash chip: built from a name and its geometry, reached through
// one TLM target socket, which takes the operations in
// socpuppet/models/nand_link.h. How it must behave is the NAND contract
// (tests/cpp/contracts/nand_contract.h).
template <typename T>
concept NandSlot =
    std::constructible_from<T, sc_core::sc_module_name, const NandGeometry&> &&
    requires(T nand) {
      { nand.socket } -> std::convertible_to<tlm::tlm_target_socket<>&>;
    };

// A virtio device behind the virtio-mmio transport: built from a name
// alone, since the logic of every kind of device has a usable default for
// whatever else it takes (a seed, a size), as QEMU's devices do; with its
// register block reached through one TLM target socket, the driver's
// memory reached through one initiator socket, and one interrupt output. How it
// must behave is the virtio device contract
// (tests/cpp/contracts/virtio_device_contract.h).
template <typename T>
concept VirtioDeviceSlot =
    std::constructible_from<T, sc_core::sc_module_name> && requires(T device) {
      { device.cpu } -> std::convertible_to<tlm::tlm_target_socket<>&>;
      { device.dma } -> std::convertible_to<tlm::tlm_initiator_socket<>&>;
      { device.irq } -> std::convertible_to<sc_core::sc_out<bool>&>;
    };

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_SLOTS_H_
