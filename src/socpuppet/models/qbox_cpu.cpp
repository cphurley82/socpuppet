#include "socpuppet/models/qbox_cpu.h"

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>

#include <async_event.h>
#include <cci_configuration>
#include <libqemu-cxx/target/riscv.h>
#include <qemu-instance.h>
#include <riscv64.h>
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/models/hart_adapter.h"
#include "socpuppet/models/hart_registers.h"
#include "socpuppet/models/tie_low.h"
#include "socpuppet/platform/failure.h"

namespace socpuppet {

namespace {

// QEMU's numbers for the two modes whose IMSIC registers it hands to the
// platform, and how it says which register (AIA_MAKE_IREG, in QEMU's
// target/riscv/cpu.h): in the low sixteen bits, the number of the IMSIC
// register selected, which is always one of an IMSIC's, from 0x70 to
// 0xFF, or kTopei for the one a claim is made through (`mtopei` or
// `stopei`, QEMU's ISELECT_IMSIC_TOPEI); and above them, the mode.
constexpr std::uint32_t kMachineMode = 3;
constexpr std::uint32_t kSupervisorMode = 1;
constexpr std::uint64_t kSelectionBits = 0xFFFF;
constexpr unsigned kModeShift = 16;
constexpr std::uint64_t kModeBits = 0x3;
constexpr std::uint64_t kTopei = 0x200;

// The numbers RISC-V gives the interrupts the adapter has inputs for:
// their bits in the interrupt-pending register, which is how QBox numbers
// its CPU's interrupt inputs.
constexpr unsigned kMachineTimerInterrupt = 7;
constexpr unsigned kSupervisorExternalInterrupt = 9;
constexpr unsigned kMachineExternalInterrupt = 11;

// The Core below is QBox's cpu_riscv64, in a QEMU built for 64-bit RISC-V
// only (tools/build_qbox.py), the width Linux and the host boards are. The
// 32-bit boards keep the dbt_rise_cpu.
void RefuseAnyWidthBut64(std::uint64_t xlen) {
  if (xlen == 64) return;
  throw std::invalid_argument(
      R"(A "qbox_cpu" is a 64-bit CPU, and an "xlen" of )" +
      std::to_string(xlen) +
      R"( was asked for. A 32-bit CPU is a "dbt_rise_cpu".)");
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
  // An instruction is 2^7 = 128 ns of simulated time, the nearest QEMU
  // can count to DbtRiseCpu's 100 (it counts in powers of two of a
  // nanosecond). At its default of 1 ns, firmware that waits by spinning
  // spins a hundred times as many instructions for the same wait, and
  // Zephyr's timer and scheduler suites ran out of twister's time.
  constexpr int k128NanosecondsAnInstruction = 7;
  set("qemu.icount_mips_shift", cci::cci_value(k128NanosecondsAnInstruction));
  set("core.resetvec", cci::cci_value(reset_vector));
  // QBox logs what it does as warnings ("QOM Device creation", "Start
  // reset"), which would be among the first lines a run prints. Its
  // errors are reported whatever the level (SCP_ERR in its scp/report.h),
  // and its warnings only above level 0, so 0 it is, for the CPU and
  // everything of QBox's under it: the level is looked up by a
  // component's path, then its parents'.
  constexpr int kNoWarnings = 0;
  set("log_level", cci::cci_value(kNoWarnings));
  // The Advanced Interrupt Architecture's registers for both modes, which
  // reach an IMSIC through `csr`. QEMU has them whether or not there is one,
  // because nothing can be asked whether there is before the run starts.
  set("core.smaia", cci::cci_value(true));
  set("core.ssaia", cci::cci_value(true));
  // No Sstc, supervisor mode's own timer compare, which DbtRiseCpu has not
  // got either. QEMU times `stimecmp` with its own ACLINT, which it takes
  // the argument of the `time` hook to be, and here that is the adapter:
  // it would read a frequency from the wrong object and divide by it
  // (docs/upstream.md). Supervisor mode's timer is then the machine
  // timer's, which OpenSBI sets through `mtimecmp`.
  set("core.sstc", cci::cci_value(false));
  // `core.gdb_port` is left unset on purpose: QBox would start QEMU's GDB
  // server as the platform is built, before the CPU is held, and a
  // debugger that attached and said continue before the run began would
  // be lost. The server is started once the CPU is held
  // (QboxCpu::HeldAtItsFirstInstruction). And not QEMU's -S, its own way
  // of holding a CPU for a debugger: a machine never started leaves QEMU's
  // CPU loop waiting on a thread's condition variable, which as a
  // coroutine is SystemC's thread, and a debugger's read of memory, served
  // from that thread, then waits for ever (docs/upstream.md).
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

  // Has QEMU hand the registers that are really an IMSIC's to `csr`, for
  // machine mode and for supervisor mode. QEMU reads and writes such a
  // register in one go, with a mask that says which bits are written, and
  // through `csr` that is a read and then, if there is anything to write,
  // a write. A patch exports the hook (docs/upstream.md).
  void AnswerTheImsicsRegistersThroughCsr() {
    qemu::CpuRiscv64 cpu(core_.get_qemu_dev());
    for (const std::uint32_t mode : {kMachineMode, kSupervisorMode}) {
      cpu.set_aia_ireg_rmw_fn(
          mode,
          [](void* core, std::uint64_t reg, std::uint64_t* value,
             std::uint64_t new_value, std::uint64_t write_mask) {
            return static_cast<Core*>(core)->ReadAndWriteThroughCsr(
                       reg, *value, new_value, write_mask)
                       ? 0
                       : -1;
          },
          this);
    }
  }

  void SetReset(bool high) { core_.reset->write(high); }

  // Tells QEMU's CPU to stop, which its loop does before it runs anything
  // more, yielding to SystemC, so a debugger can read registers and
  // memory meanwhile. ⚠️ Telling it kicks the CPU, which notifies an event
  // at once: not before the simulation runs.
  void Halt() { core_.halt->write(true); }

  // 🎓 A kernel with nothing scheduled ends the run. With a channel
  // attached as suspending it waits instead for something from outside,
  // which while the CPU is held for a debugger is the debugger's read of
  // memory, served on SystemC's thread, or its continue, which kicks the
  // CPU. Attaching again is attaching.
  void KeepTheKernelWaiting() { held_.async_attach_suspending(); }
  void LetTheKernelGo() { held_.async_detach_suspending(); }

  // Has QBox tell `told` on SystemC's thread, as QEMU's machine stops for
  // the debugger and runs again (a patch: docs/upstream.md).
  void HearWhenTheMachineStopsOrRuns(std::function<void(bool stopped)> told) {
    core_.set_machine_state_callback(std::move(told));
  }

  // Starts QEMU's own GDB server on the port.
  void StartTheGdbServer(std::uint16_t port) {
    instance_.get().start_gdb_server("tcp::" + std::to_string(port));
  }
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
  static void CatchUpIfPastTheQuantum(sc_core::sc_time& delay) {
    if (delay <= tlm::tlm_global_quantum::instance().get()) return;
    sc_core::wait(delay);
    delay = sc_core::SC_ZERO_TIME;
  }
  bool get_direct_mem_ptr(tlm::tlm_generic_payload& transaction,
                          tlm::tlm_dmi& dmi) {
    return cpu_.socket->get_direct_mem_ptr(transaction, dmi);
  }
  // A debugger's access, before the CPU has run far enough to reach the
  // memory directly. ⚠️ QBox judges it by the payload's response status,
  // which a debug transport need not set: TLM's answer is the count of
  // bytes moved. A target that moved every byte answered.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    const unsigned moved = cpu_.socket->transport_dbg(transaction);
    if (moved == transaction.get_data_length() &&
        transaction.get_response_status() == tlm::TLM_INCOMPLETE_RESPONSE) {
      transaction.set_response_status(tlm::TLM_OK_RESPONSE);
    }
    return moved;
  }

  // The timer's count at the time the CPU has got to, with its lead as
  // QBox works it out before a bus access.
  std::uint64_t Time() {
    return ReadTheTimer(cpu_.time, core_.initiator_get_local_time());
  }

  // QEMU's read-and-write of the IMSIC register `reg` names, through
  // `csr`. Returns whether there was such a register there.
  bool ReadAndWriteThroughCsr(std::uint64_t reg, std::uint64_t& value,
                              std::uint64_t new_value,
                              std::uint64_t write_mask) {
    const bool machine = ((reg >> kModeShift) & kModeBits) == kMachineMode;
    const std::uint64_t selected = reg & kSelectionBits;
    const std::uint64_t address =
        selected == kTopei
            ? HartRegisterAddress(machine ? kMtopei : kStopei)
            : HartRegisterAddress(machine ? kMireg : kSireg,
                                  static_cast<std::uint32_t>(selected));
    const sc_core::sc_time lead = core_.initiator_get_local_time();
    const std::optional<std::uint64_t> read =
        ReadHartRegister(cpu_.csr, address, lead);
    if (!read) return false;
    value = *read;
    return write_mask == 0 ||
           WriteHartRegister(cpu_.csr, address,
                             (value & ~write_mask) | (new_value & write_mask),
                             lead);
  }

  QboxCpu& cpu_;
  tlm_utils::simple_target_socket<Core> from_core_{"from_core"};
  // What keeps the kernel waiting while the CPU is held for a debugger.
  gs::async_event held_{/*start_attached=*/false};
  QemuInstanceManager manager_{"qemu_manager"};
  QemuInstance instance_{"qemu", &manager_, QemuInstance::Target::RISCV64};
  cpu_riscv64 core_{"core", instance_, /*hartid=*/0};
};

QboxCpu::QboxCpu(const sc_core::sc_module_name& name, std::uint64_t xlen,
                 std::uint64_t reset_vector, std::uint16_t gdb_port)
    : sc_module(name),
      gdb_port_(gdb_port),
      core_(MakeCore(*this, xlen, reset_vector)) {
  socket.register_invalidate_direct_mem_ptr(
      this, &QboxCpu::invalidate_direct_mem_ptr);
  // Once, in the first delta cycle, before QBox's thread runs the CPU; and
  // the rest once the board has settled.
  if (gdb_port != 0) {
    core_->HearWhenTheMachineStopsOrRuns(
        [this](bool stopped) { OnTheMachineStoppedOrRunning(stopped); });
    SC_METHOD(HoldForTheDebugger);
    SC_THREAD(HoldOnceTheBoardHasSettled);
    SC_THREAD(HoldTheClock);
  }
  // A thread, because QBox's CPU waits while it finishes a reset.
  SC_THREAD(OnReset);
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

void QboxCpu::end_of_elaboration() {
  core_->AnswerTimeFromTheTimer();
  core_->AnswerTheImsicsRegistersThroughCsr();
}

// The CPU is held before its first instruction, as DbtRiseCpu waits for a
// debugger, from a method process in the first delta cycle: the kernel
// runs the method processes of a delta cycle before its thread processes,
// so this lands before QBox's thread runs the CPU. A debugger that
// attaches pauses QEMU's machine, and its continue starts the machine
// again, which lets the CPU go.
void QboxCpu::HoldForTheDebugger() {
  core_->Halt();
  core_->KeepTheKernelWaiting();
  held_ = true;
}

// Once the board has done all it does before any time passes, which may
// have raised the CPU's reset through any number of stages: with the reset
// low, the CPU is held at its first instruction. With it high, OnReset()
// sees to it at the release. 🎓 A reset raised at power-on rises before any
// time passes, so the wait is for its rise or for the smallest step of
// time, whichever comes first. The CPU has been halted since the first
// delta cycle, so the step costs it nothing, and the board is found one
// step on. ⚠️ The rise ends the wait so that this is done before OnReset()
// can hold the clock at a release, which would keep the step from coming;
// and a CPU the debugger has let go by then is not held again.
void QboxCpu::HoldOnceTheBoardHasSettled() {
  wait(sc_core::sc_get_time_resolution(), reset.posedge_event());
  if (!reset.read() && held_) HeldAtItsFirstInstruction();
}

// The CPU is held where its firmware starts, with its reset released: time
// stands still until the debugger continues, and the port opens.
// ⚠️ The port opens only now, and not as the platform is built, as the
// DBT-RISE CPU's does: a debugger that attached earlier would find a CPU
// not yet held, or still in reset, and a continue said then would run the
// CPU through the board's reset of it. So a debugger attaches second.
void QboxCpu::HeldAtItsFirstInstruction() {
  hold_the_clock_ = true;
  clock_.notify();
  if (listening_) return;
  listening_ = true;
  core_->StartTheGdbServer(gdb_port_);
}

// QEMU's machine has stopped for the debugger, at a breakpoint, as it
// attached or as it paused the CPU, and time stands still; or the debugger
// has said continue, and time moves on. QBox tells of it on SystemC's
// thread, and the notification is immediate, so the clock is held before
// the kernel can move time on or end the run for want of anything to do.
void QboxCpu::OnTheMachineStoppedOrRunning(bool stopped) {
  if (stopped) {
    core_->KeepTheKernelWaiting();
  } else {
    held_ = false;
    core_->LetTheKernelGo();
  }
  hold_the_clock_ = stopped;
  clock_.notify();
}

// 🎓 sc_suspend_all() keeps the kernel from moving time on, while it still
// takes what comes from outside, and sc_unsuspend_all() undoes it; the two
// count, and are paired by the process that calls them, so one thread
// makes every call.
void QboxCpu::HoldTheClock() {
  bool held = false;
  for (;;) {
    wait(clock_);
    if (hold_the_clock_ && !held) {
      sc_core::sc_suspend_all();
      ++CpusHoldingTheClock();
      held = true;
    } else if (!hold_the_clock_ && held) {
      --CpusHoldingTheClock();
      sc_core::sc_unsuspend_all();
      held = false;
    }
  }
}

void QboxCpu::invalidate_direct_mem_ptr(sc_dt::uint64 start,
                                        sc_dt::uint64 end) {
  core_->InvalidateDirectMemory(start, end);
}

// QBox can wait while it lets the CPU out of reset, and the line can have
// gone high again meanwhile, unseen: so the line is passed on until what
// was passed on is what it is.
void QboxCpu::OnReset() {
  for (;;) {
    wait(reset.value_changed_event());
    bool passed_on = false;
    do {
      passed_on = reset.read();
      core_->SetReset(passed_on);
    } while (reset.read() != passed_on);
    // QBox answers a release by resuming QEMU's CPU, which would undo the
    // hold: the CPU waits for the debugger at its first instruction after
    // the reset, as DbtRiseCpu does, so it is held again, with the clock.
    if (!passed_on && held_) {
      core_->Halt();
      HeldAtItsFirstInstruction();
    }
  }
}

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
