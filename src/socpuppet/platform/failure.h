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

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_FAILURE_H_
