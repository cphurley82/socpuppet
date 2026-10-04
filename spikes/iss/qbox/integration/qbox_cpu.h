#ifndef SPIKES_ISS_QBOX_INTEGRATION_QBOX_CPU_H_
#define SPIKES_ISS_QBOX_INTEGRATION_QBOX_CPU_H_

#include <cstdint>
#include <memory>
#include <string>

#include <cpu.h>
#include <qemu-instance.h>
#include <riscv32.h>
#include <riscv64.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

namespace spike {

// QBox's QEMU-backed RISC-V CPU, fitted to the spike's CPU slot.
//
// Each CPU here gets a QEMU instance of its own, which is how a 64-bit
// and a 32-bit CPU share a process: QBox loads one copy of QEMU per word
// size. QEMU runs as a coroutine on the SystemC thread and counts
// instructions for time (QBox's deterministic configuration).
//
// QBox's components are configured through CCI parameters, set by name
// before the component is built.
class QboxCpu : public sc_core::sc_module {
 public:
  tlm_utils::simple_initiator_socket<QboxCpu> socket{"socket"};
  sc_core::sc_in<bool> irq{"irq"};
  sc_core::sc_in<bool> reset{"reset"};

  QboxCpu(const sc_core::sc_module_name& name, std::uint64_t xlen,
          std::uint64_t reset_pc)
      : sc_module(name),
        configured_(Configure(this->name(), reset_pc)),
        instance_("instance", &manager_,
                  xlen == 64 ? QemuInstance::Target::RISCV64
                             : QemuInstance::Target::RISCV32) {
    if (xlen == 64) {
      core_ = std::make_unique<cpu_riscv64>("core", instance_, 0);
    } else {
      core_ = std::make_unique<cpu_riscv32>("core", instance_, 0);
    }
    core_->socket.bind(from_core_);
    from_core_.register_b_transport(this, &QboxCpu::b_transport);
    from_core_.register_get_direct_mem_ptr(this, &QboxCpu::get_direct_mem_ptr);
    from_core_.register_transport_dbg(this, &QboxCpu::transport_dbg);
    socket.register_invalidate_direct_mem_ptr(
        this, &QboxCpu::invalidate_direct_mem_ptr);

    SC_METHOD(OnResetLine);
    sensitive << reset;
    dont_initialize();
    SC_THREAD(KeepTimeMoving);
  }

  void before_end_of_elaboration() override {
    if (irq.size() == 0) irq.bind(tied_low_);
    if (reset.size() == 0) reset.bind(tied_low_);
  }

 private:
  static bool Configure(const std::string& path, std::uint64_t reset_pc) {
    cci::cci_broker_handle broker = cci::cci_get_broker();
    const auto set = [&](const std::string& parameter,
                         const cci::cci_value& value) {
      broker.set_preset_cci_value(path + "." + parameter, value);
    };
    set("instance.tcg_mode", cci::cci_value(std::string("COROUTINE")));
    set("instance.sync_policy", cci::cci_value(std::string("tlm2")));
    set("instance.icount", cci::cci_value(true));
    set("core.resetvec", cci::cci_value(reset_pc));
    set("core.pmp", cci::cci_value(true));
    return true;
  }

  void OnResetLine() { core_->reset->write(reset.read()); }

  // A QBox CPU that has nothing to do (asleep in `wfi`, say) waits for an
  // event from the host, and has the kernel wait with it: simulated time
  // stops, and a run for a fixed length of time never returns. Something
  // scheduled in simulated time keeps the clock moving.
  void KeepTimeMoving() {
    for (;;) wait(tlm::tlm_global_quantum::instance().get());
  }

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
    from_core_->invalidate_direct_mem_ptr(start, end);
  }

  bool configured_;
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  tlm_utils::simple_target_socket<QboxCpu> from_core_{"from_core"};
  QemuInstanceManager manager_{"manager"};
  QemuInstance instance_;
  std::unique_ptr<QemuCpu> core_;
};

}  // namespace spike

#endif  // SPIKES_ISS_QBOX_INTEGRATION_QBOX_CPU_H_
