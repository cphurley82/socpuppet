#ifndef SPIKES_ISS_DBT_RISE_DBT_RISE_CPU_H_
#define SPIKES_ISS_DBT_RISE_DBT_RISE_CPU_H_

#include <cstdint>

#include <scc/configurer.h>
#include <sysc/core_complex.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace spike {

// DBT-RISE-RISCV's CPU (Minres), fitted to the spike's CPU slot.
//
// The CPU itself is DBT-RISE's `core_complex`. This wrapper only adapts
// its outside to the slot:
//   - core_complex has one bus socket for fetching instructions and one
//     for data; both are funnelled into the slot's single socket.
//   - It has 32 interrupt inputs; the slot's one interrupt is the machine
//     external interrupt, and the rest are tied low.
//   - It is clocked by a signal carrying the clock period, which says how
//     much simulated time one instruction takes.
//   - Its settings are CCI parameters, which need a broker to exist.
class DbtRiseCpu : public sc_core::sc_module {
 public:
  tlm_utils::simple_initiator_socket<DbtRiseCpu> socket{"socket"};
  sc_core::sc_in<bool> irq{"irq"};
  sc_core::sc_in<bool> reset{"reset"};

  // `gdb_port`, if not zero, is a TCP port on which DBT-RISE's GDB server
  // listens. The CPU then waits for a debugger before its first
  // instruction.
  DbtRiseCpu(const sc_core::sc_module_name& name, std::uint64_t xlen,
             std::uint64_t reset_pc, std::uint16_t gdb_port = 0)
      : sc_module(name) {
    // Machine mode only, with physical memory protection, which Zephyr's
    // boards for QEMU switch on.
    core_.core_type.set_value(xlen == 64 ? "rv64imac_mp" : "rv32imac_mp");
    core_.reset_address.set_value(reset_pc);
    core_.enable_instr_trace.set_value(false);
    core_.gdb_server_port.set_value(gdb_port);

    for (auto* from_core : {&from_fetch_, &from_data_}) {
      from_core->register_b_transport(this, &DbtRiseCpu::b_transport);
      from_core->register_get_direct_mem_ptr(this,
                                             &DbtRiseCpu::get_direct_mem_ptr);
      from_core->register_transport_dbg(this, &DbtRiseCpu::transport_dbg);
    }
    socket.register_invalidate_direct_mem_ptr(
        this, &DbtRiseCpu::invalidate_direct_mem_ptr);
    core_.ibus.bind(from_fetch_);
    core_.dbus.bind(from_data_);

    core_.clk_i.bind(clock_period_);
    core_.rst_i.bind(reset);
    for (unsigned line = 0; line < core_.clint_irq_i.size(); ++line) {
      if (line == sysc::riscv::EXT_IRQ) {
        core_.clint_irq_i[line].bind(irq);
      } else {
        core_.clint_irq_i[line].bind(tied_low_);
      }
    }
  }

  void before_end_of_elaboration() override {
    if (irq.size() == 0) irq.bind(tied_low_);
    if (reset.size() == 0) reset.bind(tied_low_);
  }

 private:
  // The two sockets of core_complex have a bus width of zero, SCC's mark
  // for "loosely timed", and only bind to their like.
  using FromCore = tlm_utils::simple_target_socket<DbtRiseCpu, scc::LT>;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    socket->b_transport(transaction, delay);
  }
  bool get_direct_mem_ptr(tlm::tlm_generic_payload& transaction,
                          tlm::tlm_dmi& dmi) {
    return socket->get_direct_mem_ptr(transaction, dmi);
  }
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return socket->transport_dbg(transaction);
  }
  void invalidate_direct_mem_ptr(sc_dt::uint64 start, sc_dt::uint64 end) {
    from_fetch_->invalidate_direct_mem_ptr(start, end);
    from_data_->invalidate_direct_mem_ptr(start, end);
  }

  // 10 MHz, the clock Zephyr's boards for QEMU are told they have.
  sc_core::sc_signal<sc_core::sc_time> clock_period_{
      "clock_period", sc_core::sc_time(100, sc_core::SC_NS)};
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  FromCore from_fetch_{"from_fetch"};
  FromCore from_data_{"from_data"};
  // The broker has to exist before the core and its parameters do.
  bool cci_ready_ = scc::init_cci();
  sysc::riscv::core_complex<> core_{"core"};
};

}  // namespace spike

#endif  // SPIKES_ISS_DBT_RISE_DBT_RISE_CPU_H_
