#ifndef SOCPUPPET_MODELS_PLIC_H_
#define SOCPUPPET_MODELS_PLIC_H_

#include <cstddef>
#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// The RISC-V platform-level interrupt controller (PLIC): where the
// interrupt lines of a platform's devices meet, and the one line to the CPU
// comes out. The firmware gives each source a priority and enables the ones
// it wants. When one interrupts, the firmware "claims" it, which says which
// source it was, and "completes" it when its handler is done.
//
// The model is borrowed: the PLIC from VPV-Peripherals (Minres). This class
// is the adapter that fits it into a socpuppet platform.
class Plic : public sc_core::sc_module {
 public:
  // Sources are numbered from 1, as the PLIC numbers them: 0 means "none".
  static constexpr std::size_t kSources = 31;

  tlm_utils::simple_target_socket<Plic> socket{"socket"};
  // The devices' interrupt lines. Source N is sources[N - 1]. One left
  // unconnected is tied low.
  sc_core::sc_vector<sc_core::sc_in<bool>> sources{"source", kSources};
  // The machine external interrupt, for a CPU's `irq`.
  sc_core::sc_out<bool> irq{"irq"};

  explicit Plic(const sc_core::sc_module_name& name);
  ~Plic() override;

  // SystemC's last chance to bind a port. By now we know which sources
  // anyone connected.
  void before_end_of_elaboration() override;

 private:
  struct Model;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay);

  // What a source left unconnected is bound to.
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
  std::unique_ptr<Model> model_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_PLIC_H_
