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
// the way the real processor would. It is an RV64IMAC core in machine mode
// only: no floating point, and no supervisor or user mode.
//
// This class is only the adapter that fits it into a socpuppet platform.
// DBT-RISE's own headers stay out of this one, so that nothing else has to
// be compiled against them.
class DbtRiseCpu : public sc_core::sc_module {
 public:
  // Every fetch, load and store leaves through here.
  tlm_utils::simple_initiator_socket<DbtRiseCpu> socket{"socket"};

  // `reset_vector` is the address of the first instruction it executes.
  DbtRiseCpu(const sc_core::sc_module_name& name, std::uint64_t reset_vector);
  ~DbtRiseCpu() override;

 private:
  struct Core;
  std::unique_ptr<Core> core_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_DBT_RISE_CPU_H_
