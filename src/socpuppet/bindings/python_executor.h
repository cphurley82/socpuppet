#ifndef SOCPUPPET_BINDINGS_PYTHON_EXECUTOR_H_
#define SOCPUPPET_BINDINGS_PYTHON_EXECUTOR_H_

#include <exception>
#include <functional>
#include <utility>

#include <pybind11/pybind11.h>
#include <systemc>

#include "socpuppet/platform/failure.h"

namespace socpuppet {

// The one place where the simulation calls into Python.
//
// A SystemC thread process (SC_THREAD) runs on a small private stack of its
// own. CPython assumes it runs on the operating system thread's real stack:
// it measures that stack to detect runaway recursion, and debuggers and
// profilers walk it. Calling Python from a SystemC thread's stack breaks
// those assumptions.
//
// A method process (SC_METHOD) is different: the kernel calls it directly,
// on the stack of whoever called sc_start(), which is Python's own stack.
// So a thread that needs Python hands the job to this module's method
// process and waits. The hand-over uses immediate notifications, so it costs
// no simulated time and no delta cycle.
class PythonExecutor : public sc_core::sc_module {
 public:
  explicit PythonExecutor(const sc_core::sc_module_name& name)
      : sc_module(name) {
    SC_METHOD(run_job);
    sensitive << job_posted_;
    dont_initialize();
  }

  // Runs `job` on the main stack with the GIL held, and returns once it is
  // done. Call from a SystemC thread process. If the job throws (a Python
  // exception, say), the simulation is stopped with that failure and run()
  // returns false.
  bool run(std::function<void()> job) {
    // One job at a time: several threads can ask in the same delta cycle,
    // before the method process has had its turn.
    while (job_) wait(job_done_);
    job_ = std::move(job);
    job_posted_.notify();
    wait(job_done_);
    return succeeded_;
  }

 private:
  void run_job() {
    {
      // sc_start() runs with the GIL released; take it back for the job.
      pybind11::gil_scoped_acquire gil;
      try {
        job_();
        succeeded_ = true;
      } catch (...) {
        fail_simulation(std::current_exception());
        succeeded_ = false;
      }
      job_ = nullptr;
    }
    job_done_.notify();
  }

  std::function<void()> job_;
  bool succeeded_ = false;
  sc_core::sc_event job_posted_;
  sc_core::sc_event job_done_;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_BINDINGS_PYTHON_EXECUTOR_H_
