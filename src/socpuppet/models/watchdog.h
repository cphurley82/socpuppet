#ifndef SOCPUPPET_MODELS_WATCHDOG_H_
#define SOCPUPPET_MODELS_WATCHDOG_H_

#include <memory>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace socpuppet {

// A watchdog timer: a counter firmware has to keep setting back to zero,
// which resets the CPU if firmware stops. It is the one in SiFive's FE310,
// which Zephyr has a driver for (`wdt_sifive`): it counts ticks of a
// 32,768 Hz clock, compares the count shifted right by a scale against a
// compare value, and takes a key before every write.
//
// The model is borrowed: the always-on block of the FE310 from
// VPV-Peripherals (Minres), which has the watchdog's registers, and the
// watchdog itself added by a patch. This class is the adapter that fits it
// into a socpuppet platform, and brings out the watchdog's two lines. The
// block's other registers are on the same page, and do nothing.
class Watchdog : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Watchdog> socket{"socket"};
  // The watchdog's interrupt: high while it has run out and firmware has
  // not cleared the bit that says so.
  sc_core::sc_out<bool> irq{"irq"};
  // Rises when the watchdog runs out with its reset enabled: a pulse of
  // one tick of its clock. For what resets the CPU.
  sc_core::sc_out<bool> bite{"bite"};

  explicit Watchdog(const sc_core::sc_module_name& name);
  ~Watchdog() override;

 private:
  struct Model;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay);
  // Debug transport: a register as a debugger sees it, in no simulated
  // time. Returns the bytes transferred.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction);
  std::unique_ptr<Model> model_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_WATCHDOG_H_
