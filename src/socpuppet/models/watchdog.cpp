#include "socpuppet/models/watchdog.h"

#include <memory>

#include <sifive/aon.h>
#include <sifive/gen/aon_regs.h>
#include <systemc>
#include <tlm>

#include "socpuppet/models/borrowed_model.h"

namespace socpuppet {

// The borrowed block and what it needs around it. It is a whole always-on
// block: besides the watchdog it has a real-time clock, a power manager
// and an input for the board's reset button, none of which is brought
// out. The button is never pressed.
//
// The block's two outputs are the watchdog's own lines, bound straight
// through: the block writes each from one process of its own.
struct Watchdog::Model {
  explicit Model(Watchdog& owner) {
    block_.clk_i.bind(bus_clock_);
    block_.erst_n_i.bind(button_not_pressed_);
    block_.lfclkc_o.bind(slow_clock_unread_);
    block_.rst_o.bind(owner.bite);
    block_.wdog_irq_o.bind(owner.irq);
  }

 private:
  sc_core::sc_signal<sc_core::sc_time> bus_clock_{"bus_clock"};
  // The reset button is active low: high is "not pressed".
  sc_core::sc_signal<bool> button_not_pressed_{"button_not_pressed", true};
  sc_core::sc_signal<sc_core::sc_time> slow_clock_unread_{"slow_clock_unread"};
  // PoweredOn, for two things. The block's registers are reset as the
  // simulation starts, which is what gives the compare value its two
  // seconds. And the block's own start, which sets its reset output high
  // until the button's line has been looked at, is left out: a CPU would
  // take that for a bite.
  PoweredOn<vpvper::sifive::aon> block_{"block"};

 public:
  BorrowedSocket registers{block_.socket};
};

Watchdog::Watchdog(const sc_core::sc_module_name& name)
    : sc_module(name), model_(std::make_unique<Model>(*this)) {
  socket.register_b_transport(this, &Watchdog::b_transport);
  socket.register_transport_dbg(this, &Watchdog::transport_dbg);
}

Watchdog::~Watchdog() = default;

void Watchdog::b_transport(tlm::tlm_generic_payload& transaction,
                           sc_core::sc_time& delay) {
  model_->registers.Access(transaction, delay);
}

unsigned Watchdog::transport_dbg(tlm::tlm_generic_payload& transaction) {
  return model_->registers.DebugAccess(transaction);
}

}  // namespace socpuppet
