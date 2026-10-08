#ifndef SOCPUPPET_MODELS_INTERRUPT_LINES_H_
#define SOCPUPPET_MODELS_INTERRUPT_LINES_H_

#include <cstddef>

#include <systemc>

#include "socpuppet/core/interrupt_requests.h"

namespace socpuppet {

// Drives a device's interrupt lines from what the device asks for.
//
// A line is high while the device is asking on its vector. When the host
// acknowledges, the line falls, and if the device still has something to
// say it rises again one delta cycle after. (A delta cycle is one round of
// the simulator letting every process that is ready run, with no time
// passing.) The host is told about an interrupt when the line rises, so
// the fall has to be there to see.
//
// A device has one of these as a member and calls Update() whenever what
// the lines should say may have changed.
class InterruptLines : public sc_core::sc_module {
 public:
  // `lines` are the device's own output ports, one per vector.
  InterruptLines(const sc_core::sc_module_name& name,
                 sc_core::sc_vector<sc_core::sc_out<bool>>& lines,
                 InterruptRequests& requests)
      : sc_module(name), lines_(lines), requests_(requests) {
    SC_METHOD(Drive);
    sensitive << changed_;
    dont_initialize();
    SC_METHOD(Rearm);
    sensitive << rearm_;
    dont_initialize();
  }

  // Drives the lines in this delta cycle, so that a fall is visible in the
  // next one, before the device can have done anything more.
  void Update() { changed_.notify(); }

 private:
  // The only process that writes the lines. A SystemC signal takes one
  // writer, and both the host's access and the device's own work change
  // what the lines should say.
  void Drive() {
    for (std::size_t line = 0; line < lines_.size(); ++line) {
      lines_[line].write(requests_.Interrupting(line));
    }
    // The lines now show the fall. One delta cycle on, they may rise again.
    if (requests_.Quieted()) rearm_.notify(sc_core::SC_ZERO_TIME);
  }

  // Rearming lets everything that was quieted ask again, which is right
  // only if each line has already been seen low. It has: this runs a delta
  // cycle after Drive wrote the fall, and the kernel runs it before the
  // host's next access in that delta, which could quiet another request.
  void Rearm() {
    requests_.Rearm();
    changed_.notify();
  }

  sc_core::sc_vector<sc_core::sc_out<bool>>& lines_;
  InterruptRequests& requests_;
  // Notified when what the lines should say may have changed.
  sc_core::sc_event changed_;
  // Notified a delta cycle after the lines fell for an acknowledgement.
  sc_core::sc_event rearm_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_MODELS_INTERRUPT_LINES_H_
