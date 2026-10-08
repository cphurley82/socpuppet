#ifndef TESTS_CPP_SUPPORT_INTERRUPT_SOURCE_H_
#define TESTS_CPP_SUPPORT_INTERRUPT_SOURCE_H_

#include <functional>
#include <utility>

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

// A device that interrupts, for tests. `body` runs in a simulation thread
// and can raise the line and wait. Any write to the device lowers the line
// again, the way a handler quiets a real device by writing to one of its
// registers, and is counted.
class InterruptSource : public sc_core::sc_module {
 public:
  tlm_utils::simple_target_socket<InterruptSource> socket{"socket"};
  sc_core::sc_out<bool> line{"line"};

  InterruptSource(const sc_core::sc_module_name& name,
                  std::function<void(InterruptSource&)> body)
      : sc_module(name), body_(std::move(body)) {
    socket.register_b_transport(this, &InterruptSource::b_transport);
    SC_THREAD(Run);
    SC_METHOD(DriveTheLine);
    sensitive << asking_changed_;
    dont_initialize();
  }

  void Raise() {
    asking_ = true;
    asking_changed_.notify();
  }
  void WaitFor(const sc_core::sc_time& duration) { wait(duration); }

  // How many times the device has been quieted.
  int TimesQuieted() const { return times_quieted_; }

 private:
  void Run() { body_(*this); }

  void b_transport(tlm::tlm_generic_payload& transaction, sc_core::sc_time&) {
    if (transaction.is_write()) {
      ++times_quieted_;
      asking_ = false;
      asking_changed_.notify();
    }
    transaction.set_response_status(tlm::TLM_OK_RESPONSE);
  }

  // The only process that writes the line. The device's own thread raises
  // it and the master's process, writing a register, lowers it, and a wire
  // takes one driver.
  void DriveTheLine() { line.write(asking_); }

  std::function<void(InterruptSource&)> body_;
  bool asking_ = false;
  // Notified at once, so that the line is written in the same delta cycle
  // as the raise or the quieting write.
  sc_core::sc_event asking_changed_;
  int times_quieted_ = 0;
};

#endif  // TESTS_CPP_SUPPORT_INTERRUPT_SOURCE_H_
