#include "socpuppet/core/rtc_logic.h"

#include <array>
#include <chrono>
#include <cstdint>
#include <optional>

#include <gtest/gtest.h>

#include "socpuppet/core/little_endian.h"
#include "socpuppet/core/time.h"
#include "socpuppet/regs/rtc.h"

namespace socpuppet {

namespace {

// 2026-10-26 at midnight, in nanoseconds since 1970: the time of day the
// tests give the clock.
constexpr std::uint64_t kGiven = 1'792'972'800'000'000'000ULL;
// A second, as a time of day counts it, and as simulated time does.
constexpr std::uint64_t kASecond = 1'000'000'000ULL;
constexpr Picoseconds Seconds(std::uint64_t count) {
  return std::chrono::duration_cast<Picoseconds>(std::chrono::seconds{count});
}
constexpr Picoseconds kStart{0};

std::uint32_t Read32(RtcLogic& rtc, std::uint64_t offset, Picoseconds now) {
  std::array<std::uint8_t, 4> out{};
  EXPECT_TRUE(rtc.ReadRegister(offset, out, now));
  return LoadLittleEndian<std::uint32_t>(out);
}

// A write, and Advance after it, as the clock's wrapper makes them.
void Write32(RtcLogic& rtc, std::uint64_t offset, std::uint32_t value,
             Picoseconds now) {
  std::array<std::uint8_t, 4> in{};
  StoreLittleEndian(value, in);
  EXPECT_TRUE(rtc.WriteRegister(offset, in, now));
  rtc.Advance(now);
}

// A time, from the low and high halves of a register pair.
std::uint64_t Joined(std::uint32_t low, std::uint32_t high) {
  return static_cast<std::uint64_t>(high) << 32U | low;
}

// The time, as Linux's rtc-goldfish reads it: the low half, and then the
// high half, which the read of the low half kept.
std::uint64_t ReadTime(RtcLogic& rtc, Picoseconds now) {
  const std::uint32_t low = Read32(rtc, RTC_TIME_LOW, now);
  return Joined(low, Read32(rtc, RTC_TIME_HIGH, now));
}

std::uint64_t ReadAlarm(RtcLogic& rtc, Picoseconds now) {
  const std::uint32_t low = Read32(rtc, RTC_ALARM_LOW, now);
  return Joined(low, Read32(rtc, RTC_ALARM_HIGH, now));
}

// Sets the time, as rtc-goldfish does: the high half, and then the low.
void SetTime(RtcLogic& rtc, std::uint64_t time, Picoseconds now) {
  Write32(rtc, RTC_TIME_HIGH, static_cast<std::uint32_t>(time >> 32U), now);
  Write32(rtc, RTC_TIME_LOW, static_cast<std::uint32_t>(time), now);
}

// Sets the alarm, as rtc-goldfish does: the high half, and then the low.
void SetAlarm(RtcLogic& rtc, std::uint64_t time, Picoseconds now) {
  Write32(rtc, RTC_ALARM_HIGH, static_cast<std::uint32_t>(time >> 32U), now);
  Write32(rtc, RTC_ALARM_LOW, static_cast<std::uint32_t>(time), now);
}

void EnableTheInterrupt(RtcLogic& rtc) {
  Write32(rtc, RTC_IRQ_ENABLED, RTC_IRQ_ENABLED_ENABLED, kStart);
}

TEST(AClockGivenATime, ReadsAsThatTimeAndTheTimeSimulatedSince) {
  RtcLogic rtc{kGiven};

  EXPECT_EQ(ReadTime(rtc, Seconds(3)), kGiven + (3 * kASecond));
}

// So that a carry from the low half into the high one between the two
// reads cannot tear the time.
TEST(AClocksHighHalf, IsAsItWasWhenTheLowHalfWasRead) {
  RtcLogic rtc{0xFFFF'FFFFULL};

  const std::uint32_t low = Read32(rtc, RTC_TIME_LOW, kStart);
  const std::uint32_t high = Read32(rtc, RTC_TIME_HIGH, Seconds(1));

  EXPECT_EQ(low, 0xFFFF'FFFFU);
  EXPECT_EQ(high, 0U);
}

TEST(AClockSetToATime, CountsOnFromIt) {
  RtcLogic rtc{kGiven};

  SetTime(rtc, kGiven + (100 * kASecond), Seconds(1));

  EXPECT_EQ(ReadTime(rtc, Seconds(3)), kGiven + (102 * kASecond));
}

TEST(AnAlarmGivenATime, ReadsAsSetAndReadsBackThatTime) {
  RtcLogic rtc{kGiven};

  SetAlarm(rtc, kGiven + kASecond, kStart);

  EXPECT_EQ(Read32(rtc, RTC_ALARM_STATUS, kStart), RTC_ALARM_STATUS_SET);
  EXPECT_EQ(ReadAlarm(rtc, kStart), kGiven + kASecond);
}

TEST(AnAlarmThatIsTakenOff, IsNotSetAndIsNotWaitedFor) {
  RtcLogic rtc{kGiven};
  SetAlarm(rtc, kGiven + kASecond, kStart);

  Write32(rtc, RTC_CLEAR_ALARM, 1, kStart);

  EXPECT_EQ(Read32(rtc, RTC_ALARM_STATUS, kStart), 0U);
  EXPECT_EQ(rtc.Advance(kStart), std::nullopt);
}

TEST(AnAlarmThatIsSet, IsWaitedForUntilItsTime) {
  RtcLogic rtc{kGiven};
  SetAlarm(rtc, kGiven + (5 * kASecond), kStart);

  EXPECT_EQ(rtc.Advance(Seconds(2)), Seconds(5));
}

TEST(AnAlarmWhoseTimeHasCome, GoesOffAndIsNoLongerSet) {
  RtcLogic rtc{kGiven};
  EnableTheInterrupt(rtc);
  SetAlarm(rtc, kGiven + kASecond, kStart);

  rtc.Advance(Seconds(1));

  EXPECT_TRUE(rtc.Interrupting());
  EXPECT_EQ(Read32(rtc, RTC_ALARM_STATUS, Seconds(1)), 0U);
}

TEST(AnAlarmWhoseTimeHasNotCome, DoesNotGoOff) {
  RtcLogic rtc{kGiven};
  EnableTheInterrupt(rtc);
  SetAlarm(rtc, kGiven + kASecond, kStart);

  rtc.Advance(Seconds(1) - Picoseconds{1'000});

  EXPECT_FALSE(rtc.Interrupting());
}

TEST(AnAlarmSetForATimeThatHasPassed, GoesOffAtOnce) {
  RtcLogic rtc{kGiven};
  EnableTheInterrupt(rtc);

  SetAlarm(rtc, kGiven - kASecond, kStart);

  EXPECT_TRUE(rtc.Interrupting());
}

TEST(AClockSetPastItsAlarm, GoesOffAtOnce) {
  RtcLogic rtc{kGiven};
  EnableTheInterrupt(rtc);
  SetAlarm(rtc, kGiven + (10 * kASecond), kStart);

  SetTime(rtc, kGiven + (20 * kASecond), kStart);

  EXPECT_TRUE(rtc.Interrupting());
}

TEST(AnAlarmThatWentOffWithTheInterruptDisabled, InterruptsOnceItIsEnabled) {
  RtcLogic rtc{kGiven};
  SetAlarm(rtc, kGiven + kASecond, kStart);
  rtc.Advance(Seconds(1));
  const bool before = rtc.Interrupting();

  Write32(rtc, RTC_IRQ_ENABLED, RTC_IRQ_ENABLED_ENABLED, Seconds(1));

  EXPECT_FALSE(before);
  EXPECT_TRUE(rtc.Interrupting());
}

TEST(AClocksRaisedInterrupt, IsClearedByAWriteToClearInterrupt) {
  RtcLogic rtc{kGiven};
  EnableTheInterrupt(rtc);
  SetAlarm(rtc, kGiven + kASecond, kStart);
  rtc.Advance(Seconds(1));
  const bool before = rtc.Interrupting();

  Write32(rtc, RTC_CLEAR_INTERRUPT, 1, Seconds(1));

  EXPECT_TRUE(before);
  EXPECT_FALSE(rtc.Interrupting());
}

TEST(AClocksInterruptEnable, ReadsBackAsWritten) {
  RtcLogic rtc{kGiven};

  EnableTheInterrupt(rtc);

  EXPECT_EQ(Read32(rtc, RTC_IRQ_ENABLED, kStart), RTC_IRQ_ENABLED_ENABLED);
}

}  // namespace

}  // namespace socpuppet
