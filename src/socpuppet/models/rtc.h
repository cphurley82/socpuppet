#ifndef SOCPUPPET_MODELS_RTC_H_
#define SOCPUPPET_MODELS_RTC_H_

#include <cstdint>
#include <optional>
#include <span>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

#include "socpuppet/core/rtc_logic.h"
#include "socpuppet/core/time.h"
#include "socpuppet/platform/time_conversion.h"

namespace socpuppet {

// A real-time clock: the Goldfish real-time clock, which Linux's
// `rtc-goldfish` drives. This is the SystemC wrapper, and the logic is in
// RtcLogic.
//
// `cpu` is its register block, and `irq` its interrupt, up when its alarm
// has gone off while firmware has the interrupt enabled. Its time of day
// is the one it was given, as nanoseconds since 1970, and as much again as
// the simulation has gone on.
class Rtc : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<Rtc> cpu{"cpu"};
  sc_core::sc_out<bool> irq{"irq"};

  // `time_ns` is the time of day as the simulation starts.
  Rtc(const sc_core::sc_module_name& name, std::uint64_t time_ns)
      : sc_module(name), logic_(time_ns) {
    cpu.register_b_transport(this, &Rtc::b_transport);
    // The one process that writes `irq`.
    SC_THREAD(Work);
  }

 private:
  // A register is read or written at the time the access is made, which a
  // CPU running ahead of the simulation's clock gives as its delay.
  void b_transport(tlm::tlm_generic_payload& transaction,
                   sc_core::sc_time& delay) {
    const std::span data{transaction.get_data_ptr(),
                         transaction.get_data_length()};
    const Picoseconds now = ToPicoseconds(sc_core::sc_time_stamp() + delay);
    const bool ok =
        transaction.is_read()
            ? logic_.ReadRegister(transaction.get_address(), data, now)
            : logic_.WriteRegister(transaction.get_address(), data, now);
    transaction.set_response_status(ok ? tlm::TLM_OK_RESPONSE
                                       : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    if (transaction.is_write()) work_.notify(sc_core::SC_ZERO_TIME);
  }

  // The clock's own thread: lets the alarm go off when it is due, and
  // looks again after every write, which may have set it or the time.
  void Work() {
    for (;;) {
      const std::optional<Picoseconds> next =
          logic_.Advance(ToPicoseconds(sc_core::sc_time_stamp()));
      irq.write(logic_.Interrupting());
      if (next) {
        wait(ToScTime(*next) - sc_core::sc_time_stamp(), work_);
      } else {
        wait(work_);
      }
    }
  }

  RtcLogic logic_;
  // Notified when firmware has written a register.
  sc_core::sc_event work_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_RTC_H_
