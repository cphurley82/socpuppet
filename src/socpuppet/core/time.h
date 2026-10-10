#ifndef SOCPUPPET_CORE_TIME_H_
#define SOCPUPPET_CORE_TIME_H_

#include <chrono>
#include <cstdint>

namespace socpuppet {

// Simulated time, counted in picoseconds.
using Picoseconds = std::chrono::duration<std::uint64_t, std::pico>;

// A number of nanoseconds, as a platform's description gives a time, in
// the unit the models count in.
constexpr Picoseconds Nanoseconds(std::uint64_t count) {
  return std::chrono::duration_cast<Picoseconds>(
      std::chrono::nanoseconds{count});
}

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_TIME_H_
