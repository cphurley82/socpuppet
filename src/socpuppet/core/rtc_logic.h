#ifndef SOCPUPPET_CORE_RTC_LOGIC_H_
#define SOCPUPPET_CORE_RTC_LOGIC_H_

#include <cstdint>
#include <optional>
#include <span>

#include "socpuppet/core/time.h"

namespace socpuppet {

// What a real-time clock does, with no simulator attached: the registers
// of the Goldfish real-time clock (regs/rtc.rdl), and its alarm.
//
// It has no clock of its own. It is told the simulated time with each
// call, and reads as the time of day it was given, or set to since, and as
// much again as the simulation has gone on. After any call, Advance() is
// the one thing that says when to come back. Times of day are nanoseconds
// since 1970.
class RtcLogic {
 public:
  // `time_ns` is the time of day the clock reads as the simulation starts.
  explicit RtcLogic(std::uint64_t time_ns) : start_ns_(time_ns) {}

  // Reads and writes of the register block, at simulated time `now`. Each
  // returns false, and changes nothing, if the access is refused: it is
  // not of one whole register, or it reads a register that is only
  // written. A read of TIME_LOW keeps the high half for TIME_HIGH, so is
  // not const.
  bool ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out,
                    Picoseconds now);
  bool WriteRegister(std::uint64_t offset, std::span<const std::uint8_t> in,
                     Picoseconds now);

  // Makes the alarm go off if its time has come by `now`, and says when it
  // next wants to be called: when the alarm is due, or nothing if it is
  // not set.
  std::optional<Picoseconds> Advance(Picoseconds now);

  // Whether the clock's interrupt is up: its alarm has gone off, and the
  // interrupt is enabled and not cleared.
  bool Interrupting() const { return interrupt_ && interrupt_enabled_; }

 private:
  // The time of day at simulated time `now`.
  std::uint64_t TimeOfDay(Picoseconds now) const;

  // What the clock read as the simulation started: what it was given, or
  // what makes it read as it was last set to.
  std::uint64_t start_ns_;
  // TIME_HIGH: as it was when TIME_LOW was last read, or as written.
  std::uint32_t time_high_ = 0;
  std::uint32_t alarm_low_ = 0;
  std::uint32_t alarm_high_ = 0;
  bool alarm_set_ = false;
  bool interrupt_ = false;
  bool interrupt_enabled_ = false;
};

}  // namespace socpuppet

#endif  // SOCPUPPET_CORE_RTC_LOGIC_H_
