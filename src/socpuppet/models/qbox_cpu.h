#ifndef SOCPUPPET_MODELS_QBOX_CPU_H_
#define SOCPUPPET_MODELS_QBOX_CPU_H_

#include <cstdint>
#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

namespace socpuppet {

// A 64-bit RISC-V CPU that is QEMU's: QBox (Qualcomm), which puts QEMU's
// CPUs inside a SystemC simulation. QEMU translates the firmware's
// instructions into the host's as it meets them, and runs the translation,
// where DbtRiseCpu interprets them one by one. So it is many times faster,
// and it is a second, independent hart: a program that works on one and
// not on the other says which hart to look at.
//
// QEMU is GPL-2.0, so only a build with QBox has this class
// (tools/build_qbox.sh, SOCPUPPET_QBOX_DIR). QEMU runs as a coroutine on
// SystemC's thread and counts instructions for time, so that two runs of
// one program agree.
//
// This class is only the adapter that fits it into a socpuppet platform.
// QBox's headers stay out of this one: they bring a fmt and a scp/report.h
// of their own (docs/upstream.md).
class QboxCpu : public sc_core::sc_module {
 public:
  // Every fetch, load and store leaves through here.
  tlm_utils::simple_initiator_socket<QboxCpu> socket{"socket"};
  // While high, the CPU does nothing. When it goes low, the CPU starts from
  // its reset vector. Left unconnected, it is tied low.
  sc_core::sc_in<bool> reset{"reset"};
  // The machine external interrupt. Left unconnected, it is tied low.
  sc_core::sc_in<bool> irq{"irq"};
  // The machine timer interrupt. Left unconnected, it is tied low.
  sc_core::sc_in<bool> timer_irq{"timer_irq"};

  // `xlen` is the width of its registers in bits, which must be 64: any
  // other is std::invalid_argument. `reset_vector` is the address of the
  // first instruction it executes.
  QboxCpu(const sc_core::sc_module_name& name, std::uint64_t xlen,
          std::uint64_t reset_vector);
  ~QboxCpu() override;

  // SystemC's last chance to bind a port. By now we know whether anyone
  // connected the inputs.
  void before_end_of_elaboration() override;

 private:
  struct Core;

  // QBox's parts, configured before they are built, as they must be, and
  // refused first if `xlen` is not the 64 they are built for.
  static std::unique_ptr<Core> MakeCore(QboxCpu& cpu, std::uint64_t xlen,
                                        std::uint64_t reset_vector);
  // A target taking back direct memory access it granted earlier.
  void invalidate_direct_mem_ptr(sc_dt::uint64 start, sc_dt::uint64 end);
  // Each input, passed on to QBox's CPU when it changes.
  void OnReset();
  void OnIrq();
  void OnTimerIrq();

  // What an input left unconnected is bound to.
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  std::unique_ptr<Core> core_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_QBOX_CPU_H_
