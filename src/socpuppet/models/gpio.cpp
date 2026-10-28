#include "socpuppet/models/gpio.h"

#include <array>
#include <deque>
#include <format>
#include <memory>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

#include <sifive/gen/gpio_regs.h>
#include <sifive/gpio.h>
#include <systemc>
#include <tlm/scc/signal_initiator_mixin.h>
#include <tlm/scc/signal_target_mixin.h>
#include <tlm>

#include "socpuppet/core/pin_listener.h"
#include "socpuppet/models/borrowed_model.h"

namespace socpuppet {

namespace {

using PinIn = tlm::scc::tlm_signal_logic_in;
using PinOut = tlm::scc::tlm_signal_logic_out;
using Signal = tlm::scc::tlm_signal_gp<sc_dt::sc_logic>;

// A pin, and what is on it: high, low, or nothing.
struct PinLevel {
  unsigned pin;
  std::optional<bool> level;
};

// Refuses a pin the GPIO has not, as the far end names it.
unsigned Checked(unsigned pin) {
  if (pin >= Gpio::kPins) {
    throw std::out_of_range(std::format(
        "A GPIO has pins 0 to {}, and no pin {}.", Gpio::kPins - 1, pin));
  }
  return pin;
}

}  // namespace

// The borrowed GPIO and the far end of its pins.
//
// 🎓 The GPIO drives a pin as a transaction on that pin's output socket,
// carrying a logic value: one, zero, or Z, high impedance, which is a pin
// that drives nothing. It is told what is on a pin the same way, on the
// pin's input socket.
//
// Each pin's interrupt output is bound straight through: the GPIO writes
// them from one process of its own.
struct Gpio::Model {
  explicit Model(Gpio& owner) {
    gpio_.clk_i.bind(bus_clock_);
    gpio_.rst_i.bind(reset_tied_low_);
    for (unsigned pin = 0; pin < kPins; ++pin) {
      gpio_.pins_o[pin].bind(outputs_[pin]);
      outputs_[pin].register_nb_transport(
          [this](unsigned driven, Signal& signal, tlm::tlm_phase&,
                 sc_core::sc_time&) {
            Driven(driven, signal.get_value());
            return tlm::TLM_COMPLETED;
          },
          pin);
      inputs_[pin].bind(gpio_.pins_i[pin]);
      gpio_.irq_o[pin].bind(owner.irq[pin]);
    }
    sc_core::sc_spawn_options method;
    method.spawn_method();
    method.dont_initialize();
    method.set_sensitivity(&far_end_drove_);
    sc_core::sc_spawn([this] { ApplyTheFarEndsDrives(); }, "apply_drives",
                      &method);
    sc_core::sc_spawn([this] { TellTheFarEnd(); }, "tell_the_far_end");
  }

  void OnChange(PinListener listener) {
    listeners_.push_back(std::move(listener));
  }

  // Applied a delta cycle on, by ApplyTheFarEndsDrives.
  void Drive(unsigned pin, std::optional<bool> level) {
    drives_.push_back({.pin = Checked(pin), .level = level});
    far_end_drove_.notify(sc_core::SC_ZERO_TIME);
  }

  std::optional<bool> Level(unsigned pin) const {
    return levels_[Checked(pin)];
  }

 private:
  // The GPIO has driven `pin` to `value`, from whichever process wrote
  // the register: the far end hears of it from TellTheFarEnd, since a
  // CPU's process may not wait.
  //
  // A value that is neither high nor low drives nothing: Z, which is what
  // the GPIO drives on a pin that is not an output, and X, unknown.
  void Driven(unsigned pin, const sc_dt::sc_logic& value) {
    std::optional<bool> level;
    if (value == sc_dt::Log_1) level = true;
    if (value == sc_dt::Log_0) level = false;
    if (levels_[pin] == level) return;
    levels_[pin] = level;
    changes_.push_back({.pin = pin, .level = level});
    changed_.notify(sc_core::SC_ZERO_TIME);
  }

  // The adapter's own thread, which tells the far end of each change.
  void TellTheFarEnd() {
    while (true) {
      sc_core::wait(changed_);
      // A listener may wait, and more changes come meanwhile.
      while (!changes_.empty()) {
        const auto [pin, level] = changes_.front();
        changes_.pop_front();
        for (const PinListener& listener : listeners_) listener(pin, level);
      }
    }
  }

  // A method, though it sends transactions, which TLM keeps for threads:
  // the target is the borrowed model inside this adapter, and it waits
  // only for a delay, which is never given.
  void ApplyTheFarEndsDrives() {
    for (const auto& [pin, level] : std::exchange(drives_, {})) {
      Signal signal;
      signal.set_command(tlm::TLM_WRITE_COMMAND);
      signal.set_value(level ? sc_dt::sc_logic{*level} : sc_dt::SC_LOGIC_Z);
      tlm::tlm_phase phase = tlm::BEGIN_REQ;
      sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
      inputs_[pin]->nb_transport_fw(signal, phase, delay);
    }
  }

  // What the far end has driven and the borrowed model not yet been told,
  // oldest first.
  std::deque<PinLevel> drives_;
  sc_core::sc_event far_end_drove_{"far_end_drove"};
  // What the GPIO has driven and the far end not yet been told, oldest
  // first.
  std::deque<PinLevel> changes_;
  sc_core::sc_event changed_{"changed"};
  std::vector<PinListener> listeners_;
  // What each pin drives.
  std::array<std::optional<bool>, kPins> levels_{};
  sc_core::sc_signal<sc_core::sc_time> bus_clock_{"bus_clock"};
  sc_core::sc_signal<bool> reset_tied_low_{"reset_tied_low"};
  sc_core::sc_vector<PinIn> outputs_{"output", kPins};
  sc_core::sc_vector<PinOut> inputs_{"input", kPins};
  PoweredOn<vpvper::sifive::gpio> gpio_{"gpio"};

 public:
  BorrowedSocket registers{gpio_.socket};
};

Gpio::Gpio(const sc_core::sc_module_name& name)
    : sc_module(name), model_(std::make_unique<Model>(*this)) {
  socket.register_b_transport(this, &Gpio::b_transport);
}

Gpio::~Gpio() = default;

std::optional<bool> Gpio::Level(unsigned pin) const {
  return model_->Level(pin);
}

void Gpio::Drive(unsigned pin, std::optional<bool> level) {
  model_->Drive(pin, level);
}

void Gpio::OnChange(PinListener listener) {
  model_->OnChange(std::move(listener));
}

void Gpio::b_transport(tlm::tlm_generic_payload& transaction,
                       sc_core::sc_time& delay) {
  model_->registers.Access(transaction, delay);
}

}  // namespace socpuppet
