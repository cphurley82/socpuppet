#ifndef SOCPUPPET_PLATFORM_TIME_CONVERSION_H_
#define SOCPUPPET_PLATFORM_TIME_CONVERSION_H_

#include <systemc>

#include "socpuppet/core/time.h"

namespace socpuppet {

// sc_time counts in units of the kernel's time resolution, which need not
// be a picosecond. These convert exactly, in integers.
inline std::uint64_t resolution_units_per_picosecond() {
  return sc_core::sc_time(1, sc_core::SC_PS).value();
}

inline Picoseconds to_picoseconds(const sc_core::sc_time& time) {
  return Picoseconds{time.value() / resolution_units_per_picosecond()};
}

inline sc_core::sc_time to_sc_time(Picoseconds time) {
  return sc_core::sc_time::from_value(time.count() *
                                      resolution_units_per_picosecond());
}

}  // namespace socpuppet

#endif  // SOCPUPPET_PLATFORM_TIME_CONVERSION_H_
