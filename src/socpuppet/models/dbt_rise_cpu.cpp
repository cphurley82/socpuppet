#include "socpuppet/models/dbt_rise_cpu.h"

#include <array>
#include <cstdint>
#include <format>
#include <memory>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>

#include <sysc/core_complex.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/hart_registers.h"
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
       bool has_supervisor_mode, std::uint64_t reset_vector,
       std::uint16_t gdb_port)
      : cpu_(cpu), xlen_(xlen), has_supervisor_mode_(has_supervisor_mode) {
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
    sysc::sc2core_if::rd_csr_f read_time = [this](unsigned number,
                                                  std::uint64_t& value) {
      value = number == kTimehCsr ? Time() >> 32 : Time();
      return iss::Ok;
    };
    complex_.register_csr_rd(kTimeCsr, read_time);
    if (xlen_ == 32) complex_.register_csr_rd(kTimehCsr, read_time);
  }

  // Has the core's registers that are really its IMSIC's answered through
  // `csr`, three for machine mode's interrupt file and, on a core with
  // supervisor mode, three for that mode's: the window onto a file's
  // registers and the register a claim is made through are sent on, and
  // the register that selects what the window looks at is kept here, one
  // for each mode. With no IMSIC there, each is answered with "no such
  // register", which DBT-RISE makes an illegal-instruction trap, as it
  // does for a register nobody answers for.
  void AnswerTheImsicsRegistersThroughCsr() {
    // DBT-RISE wants lvalues, and copies them.
    sysc::sc2core_if::rd_csr_f read_selection = [this](unsigned number,
                                                       std::uint64_t& value) {
      if (!HasAnImsic()) return iss::Err;
      value = SelectedFor(number);
      return iss::Ok;
    };
    sysc::sc2core_if::wr_csr_f write_selection = [this](unsigned number,
                                                        std::uint64_t value) {
      if (!HasAnImsic()) return iss::Err;
      // Twelve bits of it, which is what an access can carry.
      SelectedFor(number) =
          static_cast<std::uint32_t>(value) & kWidestSelection;
      return iss::Ok;
    };
    complex_.register_csr_rd(kMiselect, read_selection);
    complex_.register_csr_wr(kMiselect, write_selection);

    sysc::sc2core_if::rd_csr_f read = [this](unsigned number,
                                             std::uint64_t& value) {
      return ReadThroughCsr(number, value);
    };
    sysc::sc2core_if::wr_csr_f write = [this](unsigned number,
                                              std::uint64_t value) {
      return WriteThroughCsr(number, value);
    };
    for (const unsigned number : {kMireg, kMtopei}) {
      complex_.register_csr_rd(number, read);
      complex_.register_csr_wr(number, write);
    }
    if (!has_supervisor_mode_) return;

    complex_.register_csr_rd(kSiselect, read_selection);
    complex_.register_csr_wr(kSiselect, write_selection);
    for (const unsigned number : {kSireg, kStopei}) {
      complex_.register_csr_rd(number, read);
      complex_.register_csr_wr(number, write);
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

  iss::status ReadThroughCsr(unsigned number, std::uint64_t& value) {
    std::array<std::uint8_t, kHartRegisterBytes> bytes{};
    if (!ThroughCsr(tlm::TLM_READ_COMMAND, number, bytes)) return iss::Err;
    value = LoadLittleEndian<std::uint64_t>(bytes);
    return iss::Ok;
  }

  iss::status WriteThroughCsr(unsigned number, std::uint64_t value) {
    auto bytes = LittleEndianBytes(value);
    if (!ThroughCsr(tlm::TLM_WRITE_COMMAND, number, bytes)) return iss::Err;
    LetALineThatChangedBeHeard();
    return iss::Ok;
  }

  // A write to the IMSIC may have changed its interrupt line: a claim is
  // what quiets it. The core hears of a line from a method, which cannot
  // run until this thread yields, and with a quantum that is a thousand
  // instructions off. Without a yield here the core would return from its
  // handler still seeing the interrupt pending, and take it again and
  // again. DBT-RISE is patched to do the same after a bus access
  // (interrupt-after-access), with the same count: one delta cycle runs
  // the IMSIC's method and updates the signal, a second runs the core's.
  static void LetALineThatChangedBeHeard() {
    for (int delta = 0;
         delta < 2 && sc_core::sc_pending_activity_at_current_time(); ++delta) {
      sc_core::wait(sc_core::SC_ZERO_TIME);
    }
  }

  // An access to a window or to a register a claim is made through, sent
  // to whatever is at the other end of `csr`. Returns whether that had
  // such a register.
  bool ThroughCsr(tlm::tlm_command command, unsigned number,
                  std::span<std::uint8_t> data) {
    const bool is_a_window = number == kMireg || number == kSireg;
    const std::uint64_t address =
        HartRegisterAddress(number, is_a_window ? SelectedFor(number) : 0);
    // The delay means nothing to whoever answers. It is the core's lead all
    // the same, so that a trace of the socket has the access where the bus
    // accesses around it are.
    sc_core::sc_time lead = complex_.Lead();
    return Transport(cpu_.csr, command, address, data, lead) ==
           tlm::TLM_OK_RESPONSE;
  }

  // Whether there is an IMSIC at the other end of `csr`, found by reading
  // the register a claim is made through, which claims nothing. It cannot
  // be known sooner or more simply: a `csr` nobody connected is bound to
  // something that answers every access with an error, so that the socket
  // is bound says nothing, and an IMSIC cannot be asked anything before
  // the simulation runs. So it is asked once, the first time firmware
  // selects a register of one.
  bool HasAnImsic() {
    if (!has_an_imsic_) {
      std::array<std::uint8_t, kHartRegisterBytes> unused{};
      has_an_imsic_ = ThroughCsr(tlm::TLM_READ_COMMAND, kMtopei, unused);
    }
    return *has_an_imsic_;
  }

  // What firmware last selected for the mode whose selecting register or
  // window is numbered `number`. Each mode selects for itself.
  std::uint32_t& SelectedFor(unsigned number) {
    return number == kSiselect || number == kSireg ? siselect_ : miselect_;
  }

  DbtRiseCpu& cpu_;
  std::uint64_t xlen_;
  bool has_supervisor_mode_;
  // What firmware last wrote to each of the two selecting registers.
  std::uint32_t miselect_ = 0;
  std::uint32_t siselect_ = 0;
  std::optional<bool> has_an_imsic_;
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
                                   extras.supervisor_mode, reset_vector,
                                   gdb_port)) {
  socket.register_invalidate_direct_mem_ptr(
      this, &DbtRiseCpu::invalidate_direct_mem_ptr);
}

DbtRiseCpu::~DbtRiseCpu() = default;

void DbtRiseCpu::invalidate_direct_mem_ptr(sc_dt::uint64 start,
                                           sc_dt::uint64 end) {
  core_->InvalidateDirectMemory(start, end);
}

void DbtRiseCpu::end_of_elaboration() {
  core_->AnswerTimeFromTheTimer();
  core_->AnswerTheImsicsRegistersThroughCsr();
}

void DbtRiseCpu::before_end_of_elaboration() {
  TieLowIfUnconnected(reset, tied_low_);
  TieLowIfUnconnected(irq, tied_low_);
  TieLowIfUnconnected(timer_irq, tied_low_);
  TieLowIfUnconnected(supervisor_irq, tied_low_);
}

}  // namespace socpuppet
