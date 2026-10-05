#ifndef SOCPUPPET_MODELS_MACHINE_TIMER_H_
#define SOCPUPPET_MODELS_MACHINE_TIMER_H_

#include <cstdint>
#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// The RISC-V machine timer: a counter, `mtime`, that counts up at a steady
// rate, and a compare register, `mtimecmp`. The timer interrupts for as
// long as the counter is at or past the compare value, which is how an
// operating system gets its tick. The registers are where SiFive's CLINT
// has them: `mtimecmp` at 0x4000 and `mtime` at 0xBFF8, 64 bits each.
//
// The model is borrowed: the ACLINT from VPV-Peripherals (Minres). This
// class is the adapter that fits it into a socpuppet platform.
class MachineTimer : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<MachineTimer> socket{"socket"};
  // The machine timer interrupt, for a CPU's `timer_irq`.
  sc_core::sc_out<bool> irq{"irq"};

  // `frequency_hz` is how many times a second `mtime` counts up.
  MachineTimer(const sc_core::sc_module_name& name, std::uint64_t frequency_hz);
  ~MachineTimer() override;

 private:
  struct Model;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay);

  std::unique_ptr<Model> model_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_MACHINE_TIMER_H_
