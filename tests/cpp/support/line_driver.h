#ifndef TESTS_CPP_SUPPORT_LINE_DRIVER_H_
#define TESTS_CPP_SUPPORT_LINE_DRIVER_H_

#include <functional>
#include <utility>

#include <systemc>

// Drives one wire from a test: `body` runs in a simulation thread and can
// set the line and wait.
class LineDriver : public sc_core::sc_module {
 public:
  sc_core::sc_out<bool> line{"line"};

  LineDriver(const sc_core::sc_module_name& name,
             std::function<void(LineDriver&)> body)
      : sc_module(name), body_(std::move(body)) {
    SC_THREAD(Run);
  }

  void Set(bool level) { line.write(level); }
  void WaitFor(const sc_core::sc_time& duration) { wait(duration); }

 private:
  void Run() { body_(*this); }
  std::function<void(LineDriver&)> body_;
};

using Drive = std::function<void(LineDriver&)>;

#endif  // TESTS_CPP_SUPPORT_LINE_DRIVER_H_
