#include "socpuppet/models/dbt_rise_cpu.h"

#include <array>
#include <cstdint>
#include <format>
#include <memory>
#include <stdexcept>
#include <string>

#include <sysc/core_complex.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/tie_low.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

namespace {

// DBT-RISE's name for the core with registers of `xlen` bits and these
// extras. The plain one is machine mode only, with physical memory
// protection, which Zephyr's RISC-V boards switch on. A width or a
// combination socpuppet has no core for is refused. Called before the Core
// is built, so that a refusal comes before any of DBT-RISE's core exists.
const char* CoreType(std::uint64_t xlen, DbtRiseCpuExtras extras) {
  if (xlen != 32 && xlen != 64) {
    throw std::invalid_argument(
        "The \"xlen\" of a \"dbt_rise_cpu\" is the width of its "
        "registers in bits, 32 or 64, and " +
        std::to_string(xlen) + " was given.");
  }
  const bool plain = !extras.floating_point && !extras.supervisor_mode;
  const bool both = extras.floating_point && extras.supervisor_mode;
  if (plain) return xlen == 32 ? "rv32imac_mp" : "rv64imac_mp";
  if (both && xlen == 64) return "rv64gc_msu";
  throw std::invalid_argument(std::format(
      "A \"dbt_rise_cpu\" comes with neither \"floating_point\" nor "
      "\"supervisor_mode\", at an \"xlen\" of 32 or 64, or with the two "
      "together, at 64. An \"xlen\" of {} with \"floating_point\" {} and "
      "\"supervisor_mode\" {} was asked for.",
      xlen, extras.floating_point ? 1 : 0, extras.supervisor_mode ? 1 : 0));
}

// Which of the core's interrupt inputs is the supervisor external
// interrupt. DBT-RISE names the machine-mode ones and not this one.
constexpr unsigned kSupervisorExternalInterrupt = 9;

// The number of the register a hart reads the machine timer's count from,
// and of the one a 32-bit hart reads the upper half of it from.
constexpr unsigned kTimeCsr = 0xC01;
constexpr unsigned kTimehCsr = 0xC81;

// DBT-RISE's CPU. It keeps to itself how far ahead of the simulation's
// clock it has run, which an access it makes outside the bus has to carry
// as a bus access does. This lets that out.
struct CoreComplex : sysc::riscv::core_complex<> {
  using core_complex::core_complex;

  sc_core::sc_time Lead() { return quantum_keeper.get_local_time(); }
};

}  // namespace

// DBT-RISE's CPU, `core_complex`, and what it takes to fit its outside to
// ours:
//   - It has one bus socket for fetching instructions and one for data.
//     Both are funnelled into the adapter's single socket.
//   - It is clocked by a signal that carries the clock period, which says
//     how much simulated time one instruction takes.
//   - It has 32 interrupt inputs, numbered as RISC-V numbers the bits of
//     its interrupt-pending register. The machine external, machine timer
//     and supervisor external interrupts are ours to connect, and the rest
//     are tied low.
struct DbtRiseCpu::Core {
  Core(DbtRiseCpu& cpu, std::uint64_t xlen, const char* core_type,
       std::uint64_t reset_vector, std::uint16_t gdb_port)
      : cpu_(cpu), xlen_(xlen) {
    complex_.core_type.set_value(core_type);
    complex_.reset_address.set_value(reset_vector);
    // The GDB server is DBT-RISE's own, and each CPU that asks has one of
    // its own, on its own port. Zero means none.
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
      } else if (line == kSupervisorExternalInterrupt) {
        complex_.clint_irq_i[line].bind(cpu_.supervisor_irq);
      } else {
        complex_.clint_irq_i[line].bind(cpu_.tied_low_);
      }
    }
  }

  // Has the core read its `time` register from the machine timer, through
  // `time`. DBT-RISE reads it from a 64-bit input, which would not do, for
  // two reasons. A signal cannot say how far ahead of the clock its reader
  // is, so `time` would lag the timer's own register by up to a quantum.
  // And a timer that drove one would have to wake for every tick, where a
  // read costs nothing until the firmware asks.
  void AnswerTimeFromTheTimer() {
    // DBT-RISE wants an lvalue, and copies it.
    sysc::sc2core_if::rd_csr_f read_time = [this](unsigned csr,
                                                  std::uint64_t& value) {
      value = csr == kTimehCsr ? Time() >> 32 : Time();
      return iss::Ok;
    };
    complex_.register_csr_rd(kTimeCsr, read_time);
    if (xlen_ == 32) complex_.register_csr_rd(kTimehCsr, read_time);
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

  // The timer's count at the time the core has got to, or zero if there
  // is no timer at the other end of `time`.
  std::uint64_t Time() {
    std::array<std::uint8_t, 8> count{};
    sc_core::sc_time lead = complex_.Lead();
    const tlm::tlm_response_status response =
        Transport(cpu_.time, tlm::TLM_READ_COMMAND, 0, count, lead);
    return response == tlm::TLM_OK_RESPONSE
               ? LoadLittleEndian<std::uint64_t>(count)
               : 0;
  }

  DbtRiseCpu& cpu_;
  std::uint64_t xlen_;
  // One instruction takes one clock period of simulated time. 10 MHz is
  // the clock Zephyr's boards for QEMU are told they have.
  sc_core::sc_signal<sc_core::sc_time> clock_period_{
      "clock_period", sc_core::sc_time(100, sc_core::SC_NS)};
  FromCore from_fetch_{"from_fetch"};
  FromCore from_data_{"from_data"};
  // Its settings are CCI parameters, which need a broker to exist first.
  // InitLogging() creates one, and every entry point calls it.
  CoreComplex complex_{"core"};
};

DbtRiseCpu::DbtRiseCpu(const sc_core::sc_module_name& name, std::uint64_t xlen,
                       std::uint64_t reset_vector, std::uint16_t gdb_port,
                       DbtRiseCpuExtras extras)
    : sc_module(name),
      core_(std::make_unique<Core>(*this, xlen, CoreType(xlen, extras),
                                   reset_vector, gdb_port)) {
  socket.register_invalidate_direct_mem_ptr(
      this, &DbtRiseCpu::invalidate_direct_mem_ptr);
}

DbtRiseCpu::~DbtRiseCpu() = default;

void DbtRiseCpu::invalidate_direct_mem_ptr(sc_dt::uint64 start,
                                           sc_dt::uint64 end) {
  core_->InvalidateDirectMemory(start, end);
}

void DbtRiseCpu::end_of_elaboration() { core_->AnswerTimeFromTheTimer(); }

void DbtRiseCpu::before_end_of_elaboration() {
  TieLowIfUnconnected(reset, tied_low_);
  TieLowIfUnconnected(irq, tied_low_);
  TieLowIfUnconnected(timer_irq, tied_low_);
  TieLowIfUnconnected(supervisor_irq, tied_low_);
}

}  // namespace socpuppet
