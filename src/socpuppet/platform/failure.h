#pragma once

#include <exception>
#include <utility>

#include <systemc>

namespace socpuppet {

// How a model stops the simulation with an error.
//
// An exception must not escape a SystemC process: the kernel would flatten
// it into a generic report and refuse to run again. So the model parks the
// exception here and pauses the kernel instead, and whoever called run()
// throws it once the kernel has handed control back.
//
// The pause takes effect at the end of the current delta cycle, so after
// calling fail_simulation() a process must return rather than carry on.
// If several models fail in the same delta, the first failure is kept.
//
// There is one kernel per process, so one parking place is enough.
inline std::exception_ptr& parked_failure() {
  static std::exception_ptr failure;
  return failure;
}

inline void fail_simulation(std::exception_ptr failure) {
  if (!parked_failure()) parked_failure() = std::move(failure);
  sc_core::sc_pause();
}

template <typename Exception>
void fail_simulation(Exception exception) {
  fail_simulation(std::make_exception_ptr(std::move(exception)));
}

inline void rethrow_parked_failure() {
  if (std::exception_ptr failure = std::exchange(parked_failure(), nullptr)) {
    std::rethrow_exception(failure);
  }
}

}  // namespace socpuppet
