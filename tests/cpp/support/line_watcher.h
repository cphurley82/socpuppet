#ifndef TESTS_CPP_SUPPORT_LINE_WATCHER_H_
#define TESTS_CPP_SUPPORT_LINE_WATCHER_H_

#include <systemc>

// The reading end of one wire, for a test that wants to see what a
// component does with one of its outputs. It counts how many times the
// line has risen, so that a test can tell a second rise from the first
// without having to be watching at the instant it happens.
class LineWatcher : public sc_core::sc_module {
 public:
  sc_core::sc_in<bool> line{"line"};

  explicit LineWatcher(const sc_core::sc_module_name& name) : sc_module(name) {
    SC_METHOD(CountARise);
    sensitive << line.pos();
    dont_initialize();
  }

  int Rises() const { return rises_; }

  // Waits, in the calling simulation thread, until the line reads
  // `level`. Returns false if it does not within `patience`. A process
  // that has just written a register cannot read the line the device
  // drives from it in the same delta cycle: this is how to wait for it.
  bool WaitForLevel(bool level, const sc_core::sc_time& patience) {
    const sc_core::sc_time give_up = sc_core::sc_time_stamp() + patience;
    while (line.read() != level) {
      if (sc_core::sc_time_stamp() >= give_up) return false;
      sc_core::wait(give_up - sc_core::sc_time_stamp(),
                    line.value_changed_event());
    }
    return true;
  }

  // Waits, in the calling simulation thread, until the line has risen
  // `count` times in all. Returns false if it has not within `patience`.
  bool WaitForRises(int count, const sc_core::sc_time& patience) {
    const sc_core::sc_time give_up = sc_core::sc_time_stamp() + patience;
    while (rises_ < count) {
      if (sc_core::sc_time_stamp() >= give_up) return false;
      sc_core::wait(give_up - sc_core::sc_time_stamp(), counted_);
    }
    return true;
  }

 private:
  void CountARise() {
    ++rises_;
    counted_.notify(sc_core::SC_ZERO_TIME);
  }

  int rises_ = 0;
  sc_core::sc_event counted_;
};

#endif  // TESTS_CPP_SUPPORT_LINE_WATCHER_H_
