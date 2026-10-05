#include "socpuppet/models/dbt_rise_cpu.h"

#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>

#include <sysc/core_complex.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

namespace {

// DBT-RISE's name for the core with registers of `xlen` bits: machine mode
// only, with physical memory protection, which Zephyr's RISC-V boards
// switch on. Any other width is refused. Called before the Core is built,
// so that a refusal comes before any of DBT-RISE's core exists.
const char* CoreType(std::uint64_t xlen) {
  switch (xlen) {
    case 32:
      return "rv32imac_mp";
    case 64:
      return "rv64imac_mp";
    default:
      throw std::invalid_argument(
          "The \"xlen\" of a \"dbt_rise_cpu\" is the width of its "
          "registers in bits, 32 or 64, and " +
          std::to_string(xlen) + " was given.");
  }
}

// The GDB port for the CPU called `cpu`, having checked that it may have
// one. DBT-RISE has a single GDB server for the whole process, and asking
// it for a second ends the program. So the second CPU to ask is refused
// here first. Called before the Core is built, as CoreType is.
std::uint16_t GdbPortFor(const char* cpu, std::uint16_t gdb_port) {
  static bool taken = false;
  if (gdb_port == 0) return 0;
  if (taken) {
    throw std::invalid_argument(
        std::string(
            "Only one CPU in a simulation can have a GDB port, and \"") +
        cpu +
        "\" is the second to ask for one. The CPU model has a single GDB "
        "server for the whole process. Give gdb_port to the CPU you want "
        "to debug, and leave it out for the others.");
  }
  taken = true;
  return gdb_port;
}

}  // namespace

// DBT-RISE's CPU, `core_complex`, and what it takes to fit its outside to
// ours:
//   - It has one bus socket for fetching instructions and one for data.
//     Both are funnelled into the adapter's single socket.
//   - It is clocked by a signal that carries the clock period, which says
//     how much simulated time one instruction takes.
//   - It has 32 interrupt inputs, numbered as RISC-V numbers the bits of
//     its interrupt-pending register. The machine external and machine
//     timer interrupts are ours to connect, and the rest are tied low.
struct DbtRiseCpu::Core {
  Core(DbtRiseCpu& cpu, const char* core_type, std::uint64_t reset_vector,
       std::uint16_t gdb_port)
      : cpu_(cpu) {
    complex_.core_type.set_value(core_type);
    complex_.reset_address.set_value(reset_vector);
    // The GDB server is DBT-RISE's own. Zero means none.
    complex_.gdb_server_port.set_value(gdb_port);

    for (auto* from_core : {&from_fetch_, &from_data_}) {
      from_core->register_b_transport(this, &Core::b_transport);
      from_core->register_get_direct_mem_ptr(this, &Core::get_direct_mem_ptr);
      from_core->register_transport_dbg(this, &Core::transport_dbg);
    }
    complex_.ibus.bind(from_fetch_);
    complex_.dbus.bind(from_data_);

    complex_.clk_i.bind(clock_period_);
    complex_.rst_i.bind(cpu_.reset);
    for (unsigned line = 0; line < complex_.clint_irq_i.size(); ++line) {
      if (line == sysc::riscv::EXT_IRQ) {
        complex_.clint_irq_i[line].bind(cpu_.irq);
      } else if (line == sysc::riscv::TIMER_IRQ) {
        complex_.clint_irq_i[line].bind(cpu_.timer_irq);
      } else {
        complex_.clint_irq_i[line].bind(cpu_.tied_low_);
      }
    }
  }

  void InvalidateDirectMemory(sc_dt::uint64 start, sc_dt::uint64 end) {
    from_fetch_->invalidate_direct_mem_ptr(start, end);
    from_data_->invalidate_direct_mem_ptr(start, end);
  }

 private:
  // The two sockets of core_complex have a bus width of zero, SCC's mark
  // for "loosely timed", and only bind to their like.
  using FromCore = tlm_utils::simple_target_socket<Core, scc::LT>;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    cpu_.socket->b_transport(transaction, delay);
  }
  // Direct memory access (DMI): the core asks a memory for a pointer to
  // its bytes, and from then on reads and writes them without a
  // transaction each time. This is where most of a CPU model's speed
  // comes from.
  bool get_direct_mem_ptr(tlm::tlm_generic_payload& transaction,
                          tlm::tlm_dmi& dmi) {
    return cpu_.socket->get_direct_mem_ptr(transaction, dmi);
  }
  // Debug accesses: how the GDB server reads and writes memory for the
  // debugger, without the platform noticing.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return cpu_.socket->transport_dbg(transaction);
  }

  DbtRiseCpu& cpu_;
  // One instruction takes one clock period of simulated time. 10 MHz is
  // the clock Zephyr's boards for QEMU are told they have.
  sc_core::sc_signal<sc_core::sc_time> clock_period_{
      "clock_period", sc_core::sc_time(100, sc_core::SC_NS)};
  FromCore from_fetch_{"from_fetch"};
  FromCore from_data_{"from_data"};
  // Its settings are CCI parameters, which need a broker to exist first.
  // InitLogging() creates one, and every entry point calls it.
  sysc::riscv::core_complex<> complex_{"core"};
};

DbtRiseCpu::DbtRiseCpu(const sc_core::sc_module_name& name, std::uint64_t xlen,
                       std::uint64_t reset_vector, std::uint16_t gdb_port)
    : sc_module(name),
      core_(std::make_unique<Core>(*this, CoreType(xlen), reset_vector,
                                   GdbPortFor(this->name(), gdb_port))) {
  socket.register_invalidate_direct_mem_ptr(
      this, &DbtRiseCpu::invalidate_direct_mem_ptr);
}

DbtRiseCpu::~DbtRiseCpu() = default;

void DbtRiseCpu::invalidate_direct_mem_ptr(sc_dt::uint64 start,
                                           sc_dt::uint64 end) {
  core_->InvalidateDirectMemory(start, end);
}

void DbtRiseCpu::before_end_of_elaboration() {
  if (reset.size() == 0) reset.bind(tied_low_);
  if (irq.size() == 0) irq.bind(tied_low_);
  if (timer_irq.size() == 0) timer_irq.bind(tied_low_);
}

}  // namespace socpuppet
