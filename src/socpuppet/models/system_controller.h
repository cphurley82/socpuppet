#ifndef SOCPUPPET_MODELS_SYSTEM_CONTROLLER_H_
#define SOCPUPPET_MODELS_SYSTEM_CONTROLLER_H_

#include <cstdint>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/system_controller_logic.h"
#include "socpuppet/models/tie_low.h"

namespace socpuppet {

// A CPU's system controller: the block that answers the CPU's questions
// about itself and owns its reset. This is the SystemC wrapper, and what
// the registers mean is in SystemControllerLogic.
//
// 🎓 A wire has one driver, and a CPU's reset has more than one reason to
// rise. So each reason is an input here and the CPU's reset is the one
// output:
//   - `hold` is high for as long as something wants the CPU kept in reset,
//     and `reset` follows it. A die-to-die link holds the other die's CPU
//     this way until the link is trained.
//   - `bite` is a watchdog's line. When it rises, `reset` is pulsed.
//   - Firmware asks for a reset by writing a register, and `reset` is
//     pulsed for that too.
//   - Firmware switches the CPU off by writing another, and `reset` then
//     stays high for good.
// Either input may be left unconnected, and is then tied low.
class SystemController : public sc_core::sc_module {
 public:
  // The register block.
  tlm_utils::simple_target_socket<SystemController> socket{"socket"};
  sc_core::sc_in<bool> hold{"hold"};
  sc_core::sc_in<bool> bite{"bite"};
  // The CPU's reset.
  sc_core::sc_out<bool> reset{"reset"};

  // `die` and `boot_address` are what the registers of those names read.
  SystemController(const sc_core::sc_module_name& name, std::uint32_t die,
                   std::uint32_t boot_address)
      : sc_module(name), logic_(die, boot_address) {
    socket.register_b_transport(this, &SystemController::b_transport);
    socket.register_transport_dbg(this, &SystemController::transport_dbg);
    SC_METHOD(Bitten);
    sensitive << bite.pos();
    dont_initialize();
    SC_METHOD(EndThePulse);
    sensitive << pulse_over_;
    dont_initialize();
    SC_METHOD(DriveTheLine);
    sensitive << hold << changed_;
  }

 private:
  // How long a pulse of the reset lasts: ten ticks of a 10 MHz clock, which
  // is the clock a CPU on a socpuppet board has.
  static sc_core::sc_time PulseWidth() { return {1, sc_core::SC_US}; }

  void before_end_of_elaboration() override {
    TieLowIfUnconnected(hold, tied_low_);
    TieLowIfUnconnected(bite, tied_low_);
  }

  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    const bool taken =
        transaction.is_read()
            ? logic_.ReadRegister(transaction.get_address(), data)
            : logic_.WriteRegister(transaction.get_address(), data);
    transaction.set_response_status(taken ? tlm::TLM_OK_RESPONSE
                                          : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    changed_.notify();
  }

  // Debug transport: a debugger looks at the registers and changes
  // nothing, so a write, which could reset the CPU or switch it off, is not
  // taken. Returns the number of bytes transferred.
  unsigned transport_dbg(tlm::tlm_generic_payload& transaction) {
    const bool read = transaction.is_read() &&
                      logic_.ReadRegister(transaction.get_address(),
                                          {transaction.get_data_ptr(),
                                           transaction.get_data_length()});
    return read ? transaction.get_data_length() : 0;
  }

  void Bitten() {
    logic_.Bite();
    changed_.notify();
  }

  void EndThePulse() {
    logic_.EndPulse();
    changed_.notify();
  }

  // The one process that writes `reset`.
  void DriveTheLine() {
    logic_.Hold(hold.read());
    reset.write(logic_.Reset());
    // A second reason to reset while a pulse is under way does not make it
    // longer: of two times asked for, an event keeps the sooner.
    if (logic_.Pulsing()) pulse_over_.notify(PulseWidth());
  }

  SystemControllerLogic logic_;
  // Something the reset depends on has changed.
  sc_core::sc_event changed_;
  sc_core::sc_event pulse_over_;
  sc_core::sc_signal<bool> tied_low_{"tied_low"};
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_SYSTEM_CONTROLLER_H_
