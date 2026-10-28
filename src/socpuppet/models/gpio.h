#ifndef SOCPUPPET_MODELS_GPIO_H_
#define SOCPUPPET_MODELS_GPIO_H_

#include <memory>
#include <optional>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/pin_listener.h"

namespace socpuppet {

// A GPIO block: 32 general-purpose pins, each of which firmware makes an
// output it drives high or low, or an input it reads. It is the one in
// SiFive's FE310 and FU540, which Zephyr (`gpio_sifive`) and Linux
// (`gpio-sifive`) both drive.
//
// The model is borrowed: SiFive's GPIO from VPV-Peripherals (Minres), with
// its interrupts added by a patch. This class is the adapter that fits it
// into a socpuppet platform, and is the far end of its pins: whoever holds
// it sees what each pin drives, is told when that changes, and drives the
// pins firmware reads.
class Gpio : public sc_core::sc_module {
 public:
  static constexpr unsigned kPins = 32;

  tlm_utils::simple_target_socket<Gpio> socket{"socket"};
  // Each pin's interrupt: high while one of its enabled events (a rise, a
  // fall, a high level or a low level) is pending.
  sc_core::sc_vector<sc_core::sc_out<bool>> irq{"irq", kPins};

  explicit Gpio(const sc_core::sc_module_name& name);
  ~Gpio() override;

  // What the GPIO drives on `pin`: high, low, or nothing when the pin is
  // not an output. A pin past the last is std::out_of_range.
  std::optional<bool> Level(unsigned pin) const;

  // Drives `pin` from the far end: high, low, or nothing, to let it go.
  // It shows in the registers a delta cycle later, in a process of the
  // GPIO's own, since whoever calls this may be a script between two runs.
  // A pin past the last is std::out_of_range.
  void Drive(unsigned pin, std::optional<bool> level);

  // `listener` is told of each change of what a pin drives, in the order
  // they happen. It is called from a thread process of the GPIO's own,
  // never from whoever wrote the register, and may wait. It takes the place
  // of any listener before it.
  void OnChange(PinListener listener);

 private:
  struct Model;

  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay);
  std::unique_ptr<Model> model_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_GPIO_H_
