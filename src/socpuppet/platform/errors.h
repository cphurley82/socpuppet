#ifndef SOCPUPPET_PLATFORM_ERRORS_H_
#define SOCPUPPET_PLATFORM_ERRORS_H_

#include <stdexcept>

// The exceptions socpuppet raises, as the Python package's errors.py has
// them. A model stops the simulation with one through failure.h, and the
// bindings turn each into its Python counterpart.
namespace socpuppet {

// A script expected one value and read another.
class ExpectationFailed : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

// A script's read or write was refused: nothing is mapped at the address,
// or the target would not take the access.
class BusError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_ERRORS_H_
