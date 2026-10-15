#include "socpuppet/models/qbox_cpu.h"

#include <array>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>

#include <cci_configuration>
#include <libqemu-cxx/target/riscv.h>
#include <qemu-instance.h>
#include <riscv64.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/models/tie_low.h"
#include "socpuppet/platform/transport.h"

namespace socpuppet {

namespace {

// The numbers RISC-V gives the interrupts the adapter has inputs for:
// their bits in the interrupt-pending register, which is how QBox numbers
// its CPU's interrupt inputs.
constexpr unsigned kMachineTimerInterrupt = 7;
constexpr unsigned kSupervisorExternalInterrupt = 9;
constexpr unsigned kMachineExternalInterrupt = 11;

// The Core below is QBox's cpu_riscv64, in a QEMU built for 64-bit RISC-V
// only (tools/build_qbox.sh), the width Linux and the host boards are. The
// 32-bit boards keep the dbt_rise_cpu.
void RefuseAnyWidthBut64(std::uint64_t xlen) {
  if (xlen == 64) return;
  throw std::invalid_argument(
      "A \"qbox_cpu\" is a 64-bit CPU, and an \"xlen\" of " +
      std::to_string(xlen) +
      " was asked for. A 32-bit CPU is a \"dbt_rise_cpu\".");
}

// QBox's components are configured by CCI parameters, which have to be
// given values, by name, before each is built. `path` is the CPU's.
void Configure(const std::string& path, std::uint64_t reset_vector) {
  cci::cci_broker_handle broker = cci::cci_get_broker();
  const auto set = [&](const std::string& parameter,
                       const cci::cci_value& value) {
    broker.set_preset_cci_value(path + "." + parameter, value);
  };
  // QEMU as a coroutine on SystemC's thread, kept in step with the rest of
  // the platform as a TLM initiator is, by its quantum, and counting
  // instructions for time: QBox's repeatable configuration.
  set("qemu.tcg_mode", cci::cci_value(std::string("COROUTINE")));
  set("qemu.sync_policy", cci::cci_value(std::string("tlm2")));
  set("qemu.icount", cci::cci_value(true));
  set("core.resetvec", cci::cci_value(reset_vector));
}

}  // namespace

// QBox's CPU, `cpu_riscv64`, the QEMU it runs in, and what it takes to fit
// its outside to ours:
//   - Its one bus socket is funnelled into the adapter's.
//   - Its reset and its 32 interrupt inputs, numbered as RISC-V numbers
//     the bits of its interrupt-pending register, are written to, where
//     ours are read. The adapter passes each of ours on as it changes.
struct QboxCpu::Core {
  // Configure() must have been called for `cpu` first.
  explicit Core(QboxCpu& cpu) : cpu_(cpu) {
    from_core_.register_b_transport(this, &Core::b_transport);
    from_core_.register_get_direct_mem_ptr(this, &Core::get_direct_mem_ptr);
    from_core_.register_transport_dbg(this, &Core::transport_dbg);
    core_.socket.bind(from_core_);
  }

  // Has QEMU read the CPU's `time` register from the machine timer,
  // through `time`, as DbtRiseCpu does, with the CPU's lead, so that a
  // CPU ahead of the clock reads the count where it has got to. QEMU has
  // `time` read by a function of the platform's (a patch exports the
  // hook: docs/upstream.md), and without one it is an illegal instruction.
  void AnswerTimeFromTheTimer() {
    qemu::CpuRiscv64(core_.get_qemu_dev())
        .set_rdtime_fn(
            [](void* core) { return static_cast<Core*>(core)->Time(); }, this);
  }

  void SetReset(bool high) { core_.reset->write(high); }
  void SetInterrupt(unsigned number, bool high) {
    core_.irq_in[number]->write(high);
  }

  void InvalidateDirectMemory(sc_dt::uint64 start, sc_dt::uint64 end) {
    from_core_->invalidate_direct_mem_ptr(start, end);
  }

 private:
  // QBox keeps the CPU's time in QEMU's clock, which counts instructions,
  // and hands an access the CPU's lead over SystemC's clock from there. It
  // keeps that lead within the quantum only now and then, when QEMU's
  // timer for the end of a quantum fires, so a lead can be longer, and
  // with no quantum at all every access has one. And what a target adds
  // to the delay, QBox writes back and then forgets: QEMU's clock never
  // had it, and the next access reads the time from there again
  // (docs/upstream.md). So a lead longer than the quantum, before an
  // access or with what the target added, is paid here, by letting the
  // clock catch up. This runs on SystemC's thread: QEMU is a coroutine
  // there.
  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    CatchUpIfPastTheQuantum(delay);
    cpu_.socket->b_transport(transaction, delay);
    CatchUpIfPastTheQuantum(delay);
    LetALineThatChangedBeHeard();
  }
  // An access may have changed an interrupt line: a handler's write to its
  // device is what quiets it. The CPU hears of a line from a method of the
  // adapter's, which cannot run until this thread yields, and with a
  // quantum that is a thousand instructions off. Without a yield here the
  // CPU would return from its handler still seeing the interrupt pending,
  // and take it again and again. One delta cycle runs the device's method
  // and updates its line, a second runs the adapter's, as DbtRiseCpu does.
  static void LetALineThatChangedBeHeard() {
    for (int delta = 0;
         delta < 2 && sc_core::sc_pending_activity_at_current_time(); ++delta) {
      sc_core::wait(sc_core::SC_ZERO_TIME);
    }
  }
  static void CatchUpIfPastTheQuantum(sc_core::sc_time& delay) {
    if (delay <= tlm::tlm_global_quantum::instance().get()) return;
    sc_core::wait(delay);
    delay = sc_core::SC_ZERO_TIME;
  }
  bool get_direct_mem_ptr(tlm::tlm_generic_payload& transaction,
                          tlm::tlm_dmi& dmi) {
    return cpu_.socket->get_direct_mem_ptr(transaction, dmi);
  }
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    return cpu_.socket->transport_dbg(transaction);
  }

  // The timer's count at the time the CPU has got to, or zero if there is
  // no timer at the other end of `time`.
  std::uint64_t Time() {
    std::array<std::uint8_t, 8> count{};
    // The CPU's lead, as QBox works it out before a bus access.
    sc_core::sc_time lead = core_.initiator_get_local_time();
    const tlm::tlm_response_status response =
        Transport(cpu_.time, tlm::TLM_READ_COMMAND, 0, count, lead);
    return response == tlm::TLM_OK_RESPONSE
               ? LoadLittleEndian<std::uint64_t>(count)
               : 0;
  }

  QboxCpu& cpu_;
  tlm_utils::simple_target_socket<Core> from_core_{"from_core"};
  QemuInstanceManager manager_{"qemu_manager"};
  QemuInstance instance_{"qemu", &manager_, QemuInstance::Target::RISCV64};
  cpu_riscv64 core_{"core", instance_, /*hartid=*/0};
};

QboxCpu::QboxCpu(const sc_core::sc_module_name& name, std::uint64_t xlen,
                 std::uint64_t reset_vector)
    : sc_module(name), core_(MakeCore(*this, xlen, reset_vector)) {
  socket.register_invalidate_direct_mem_ptr(
      this, &QboxCpu::invalidate_direct_mem_ptr);
  SC_METHOD(OnReset);
  sensitive << reset;
  dont_initialize();
  SC_METHOD(OnIrq);
  sensitive << irq;
  dont_initialize();
  SC_METHOD(OnTimerIrq);
  sensitive << timer_irq;
  dont_initialize();
  SC_METHOD(OnSupervisorIrq);
  sensitive << supervisor_irq;
  dont_initialize();
}

QboxCpu::~QboxCpu() = default;

std::unique_ptr<QboxCpu::Core> QboxCpu::MakeCore(QboxCpu& cpu,
                                                 std::uint64_t xlen,
                                                 std::uint64_t reset_vector) {
  RefuseAnyWidthBut64(xlen);
  Configure(cpu.name(), reset_vector);
  return std::make_unique<Core>(cpu);
}

void QboxCpu::before_end_of_elaboration() {
  TieLowIfUnconnected(reset, tied_low_);
  TieLowIfUnconnected(irq, tied_low_);
  TieLowIfUnconnected(timer_irq, tied_low_);
  TieLowIfUnconnected(supervisor_irq, tied_low_);
}

void QboxCpu::end_of_elaboration() { core_->AnswerTimeFromTheTimer(); }

void QboxCpu::invalidate_direct_mem_ptr(sc_dt::uint64 start,
                                        sc_dt::uint64 end) {
  core_->InvalidateDirectMemory(start, end);
}

void QboxCpu::OnReset() { core_->SetReset(reset.read()); }

void QboxCpu::OnIrq() {
  core_->SetInterrupt(kMachineExternalInterrupt, irq.read());
}

void QboxCpu::OnTimerIrq() {
  core_->SetInterrupt(kMachineTimerInterrupt, timer_irq.read());
}

void QboxCpu::OnSupervisorIrq() {
  core_->SetInterrupt(kSupervisorExternalInterrupt, supervisor_irq.read());
}

}  // namespace socpuppet
