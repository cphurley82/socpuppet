#ifndef SOCPUPPET_MODELS_DBT_RISE_CPU_H_
#define SOCPUPPET_MODELS_DBT_RISE_CPU_H_

#include <cstdint>
#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>

namespace socpuppet {

// A RISC-V CPU. The model is DBT-RISE-RISCV's (Minres): an instruction-set
// simulator, which executes the firmware's instructions one after another
// the way the real processor would. It is an RV32IMAC or RV64IMAC core in
// machine mode only: no floating point, and no supervisor or user mode.
//
// This class is only the adapter that fits it into a socpuppet platform.
// DBT-RISE's own headers stay out of this one, so that nothing else has to
// be compiled against them.
class DbtRiseCpu : public sc_core::sc_module {
 public:
  // Every fetch, load and store leaves through here.
  tlm_utils::simple_initiator_socket<DbtRiseCpu> socket{"socket"};
  // While high, the CPU does nothing. When it goes low, the CPU starts from
  // its reset vector. Left unconnected, it is tied low.
  sc_core::sc_in<bool> reset{"reset"};
  // The machine external interrupt: what a platform's interrupt controller
  // drives. Left unconnected, it is tied low.
  sc_core::sc_in<bool> irq{"irq"};

  // `xlen` is the width of its registers in bits, 32 or 64 (XLEN is the
  // RISC-V specification's name for it). `reset_vector` is the address of
  // the first instruction it executes.
  DbtRiseCpu(const sc_core::sc_module_name& name, std::uint64_t xlen,
             std::uint64_t reset_vector);
  ~DbtRiseCpu() override;

  // SystemC's last chance to bind a port. By now we know whether anyone
  // connected the inputs.
  void before_end_of_elaboration() override;

 private:
  struct Core;

  // A target taking back direct memory access it granted earlier.
  void invalidate_direct_mem_ptr(sc_dt::uint64 start, sc_dt::uint64 end);

  // What an input left unconnected is bound to.
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  std::unique_ptr<Core> core_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_DBT_RISE_CPU_H_
