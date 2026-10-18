#ifndef SOCPUPPET_PLATFORM_FAILURE_H_
#define SOCPUPPET_PLATFORM_FAILURE_H_

#include <exception>
#include <utility>

#include <systemc>

namespace socpuppet {

// How a model stops the simulation with an error.
//
// An exception must not escape a SystemC process: the kernel would flatten
// it into a generic report and refuse to run again. So the model parks the
// exception here and pauses the kernel instead, and whoever called Run()
// throws it once the kernel has handed control back.
//
// The pause takes effect at the end of the current delta cycle, so after
// calling FailSimulation() a process must return rather than carry on.
// If several models fail in the same delta, the first failure is kept.
//
// There is one kernel per process, so one parking place is enough.
inline std::exception_ptr& ParkedFailure() {
  static std::exception_ptr failure;
  return failure;
}

inline void FailSimulation(const std::exception_ptr& failure) {
  if (!ParkedFailure()) ParkedFailure() = failure;
  sc_core::sc_pause();
}

template <typename Exception>
void FailSimulation(Exception exception) {
  FailSimulation(std::make_exception_ptr(std::move(exception)));
}

inline void RethrowParkedFailure() {
  if (std::exception_ptr failure = std::exchange(ParkedFailure(), nullptr)) {
    std::rethrow_exception(failure);
  }
}

// How many CPUs are stopped in a debugger with simulated time held with
// them. 🎓 While one is, the kernel has nothing scheduled and waits for
// something from outside it, the debugger's next word: that is not the run
// being over, and whoever asks the kernel what comes next waits with it. A
// CPU that holds the clock counts itself here while it does, and Platform
// reads it, on the one thread that runs the kernel. One count per process,
// as there is one kernel.
inline int& CpusHoldingTheClock() {
  static int count = 0;
  return count;
}

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_FAILURE_H_
