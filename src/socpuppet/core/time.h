#ifndef SOCPUPPET_CORE_TIME_H_
#define SOCPUPPET_CORE_TIME_H_

#include <chrono>
#include <cstdint>

namespace socpuppet {

// Simulated time, counted in picoseconds.
using Picoseconds = std::chrono::duration<std::uint64_t, std::pico>;

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_TIME_H_
