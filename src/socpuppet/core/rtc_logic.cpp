#include "socpuppet/core/rtc_logic.h"

#include <chrono>
#include <cstdint>
#include <optional>
#include <span>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/time.h"
#include "socpuppet/regs/rtc.h"

namespace socpuppet {

namespace {

constexpr std::size_t kRegisterBytes = 4;

constexpr std::uint64_t Joined(std::uint32_t high, std::uint32_t low) {
  return static_cast<std::uint64_t>(high) << 32 | low;
}

}  // namespace

bool RtcLogic::ReadRegister(std::uint64_t offset, std::span<std::uint8_t> out,
                            Picoseconds now) {
  if (out.size() != kRegisterBytes) return false;
  std::uint32_t value = 0;
  switch (offset) {
    case RTC_TIME_LOW: {
      const std::uint64_t time = TimeOfDay(now);
      time_high_ = static_cast<std::uint32_t>(time >> 32);
      value = static_cast<std::uint32_t>(time);
      break;
    }
    case RTC_TIME_HIGH:
      value = time_high_;
      break;
    case RTC_ALARM_LOW:
      value = alarm_low_;
      break;
    case RTC_ALARM_HIGH:
      value = alarm_high_;
      break;
    case RTC_IRQ_ENABLED:
      value = interrupt_enabled_ ? RTC_IRQ_ENABLED_ENABLED : 0U;
      break;
    case RTC_ALARM_STATUS:
      value = alarm_set_ ? RTC_ALARM_STATUS_SET : 0U;
      break;
    default:
      return false;
  }
  StoreLittleEndian(value, out);
  return true;
}

bool RtcLogic::WriteRegister(std::uint64_t offset,
                             std::span<const std::uint8_t> in,
                             Picoseconds now) {
  if (in.size() != kRegisterBytes) return false;
  const auto value = LoadLittleEndian<std::uint32_t>(in);
  switch (offset) {
    case RTC_TIME_LOW:
      // Unsigned arithmetic wraps, so a time set before the one given
      // still reads as it was set to.
      start_ns_ = Joined(time_high_, value) - (TimeOfDay(now) - start_ns_);
      return true;
    case RTC_TIME_HIGH:
      time_high_ = value;
      return true;
    case RTC_ALARM_LOW:
      alarm_low_ = value;
      alarm_set_ = true;
      return true;
    case RTC_ALARM_HIGH:
      alarm_high_ = value;
      return true;
    case RTC_IRQ_ENABLED:
      interrupt_enabled_ = (value & RTC_IRQ_ENABLED_ENABLED) != 0;
      return true;
    case RTC_CLEAR_ALARM:
      alarm_set_ = false;
      return true;
    case RTC_CLEAR_INTERRUPT:
      interrupt_ = false;
      return true;
    default:
      return false;
  }
}

std::optional<Picoseconds> RtcLogic::Advance(Picoseconds now) {
  if (!alarm_set_) return std::nullopt;
  const std::uint64_t alarm = Joined(alarm_high_, alarm_low_);
  const std::uint64_t time = TimeOfDay(now);
  if (alarm > time) return now + Nanoseconds(alarm - time);
  alarm_set_ = false;
  interrupt_ = true;
  return std::nullopt;
}

std::uint64_t RtcLogic::TimeOfDay(Picoseconds now) const {
  return start_ns_ +
         static_cast<std::uint64_t>(
             std::chrono::duration_cast<std::chrono::nanoseconds>(now).count());
}

}  // namespace socpuppet
