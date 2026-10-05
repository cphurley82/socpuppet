#include "socpuppet/models/dbt_rise_cpu.h"

#include <cstdint>
#include <memory>

#include <sysc/core_complex.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// DBT-RISE's CPU, `core_complex`, and what it takes to fit its outside to
// ours:
//   - It has one bus socket for fetching instructions and one for data.
//     Both are funnelled into the adapter's single socket.
//   - It is clocked by a signal that carries the clock period, which says
//     how much simulated time one instruction takes.
//   - Its reset and its 32 interrupt inputs are tied low.
struct DbtRiseCpu::Core {
  Core(DbtRiseCpu& cpu, std::uint64_t xlen, std::uint64_t reset_vector)
      : cpu_(cpu) {
    // Machine mode only, with physical memory protection, which Zephyr's
    // RISC-V boards switch on.
    complex_.core_type.set_value(xlen == 32 ? "rv32imac_mp" : "rv64imac_mp");
    complex_.reset_address.set_value(reset_vector);

    from_fetch_.register_b_transport(this, &Core::b_transport);
    from_data_.register_b_transport(this, &Core::b_transport);
    complex_.ibus.bind(from_fetch_);
    complex_.dbus.bind(from_data_);

    complex_.clk_i.bind(clock_period_);
    complex_.rst_i.bind(tied_low_);
    for (auto& interrupt : complex_.clint_irq_i) interrupt.bind(tied_low_);
  }

 private:
  // The two sockets of core_complex have a bus width of zero, SCC's mark
  // for "loosely timed", and only bind to their like.
  using FromCore = tlm_utils::simple_target_socket<Core, scc::LT>;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    cpu_.socket->b_transport(transaction, delay);
  }

  DbtRiseCpu& cpu_;
  // One instruction takes one clock period of simulated time. 10 MHz is
  // the clock Zephyr's boards for QEMU are told they have.
  sc_core::sc_signal<sc_core::sc_time> clock_period_{
      "clock_period", sc_core::sc_time(100, sc_core::SC_NS)};
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  FromCore from_fetch_{"from_fetch"};
  FromCore from_data_{"from_data"};
  // Its settings are CCI parameters, which need a broker to exist first.
  // InitLogging() creates one, and every entry point calls it.
  sysc::riscv::core_complex<> complex_{"core"};
};

DbtRiseCpu::DbtRiseCpu(const sc_core::sc_module_name& name, std::uint64_t xlen,
                       std::uint64_t reset_vector)
    : sc_module(name),
      core_(std::make_unique<Core>(*this, xlen, reset_vector)) {}

DbtRiseCpu::~DbtRiseCpu() = default;

}  // namespace socpuppet
