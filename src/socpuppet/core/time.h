#pragma once

#include <chrono>
#include <cstdint>

namespace socpuppet {

// Simulated time, counted in picoseconds.
using Picoseconds = std::chrono::duration<std::uint64_t, std::pico>;

}  // namespace socpuppet
