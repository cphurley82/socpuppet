/*
 * Real-time clock: the registers.
 *
 * The time of day, in nanoseconds since 1970, and an alarm at a time to come.
 *
 * Generated from regs/rtc.rdl by tools/regs.py. Do not edit: change the
 * register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_RTC_H_
#define SOCPUPPET_REGS_RTC_H_

/* How many bytes of address space the block takes. */
#define RTC_SIZE 0x1000U

/*
 * The low half of the time. Reading it keeps the high half as it was then,
 * for `TIME_HIGH`; writing it sets the time, with the high half written to
 * `TIME_HIGH` before.
 */
#define RTC_TIME_LOW 0x000U

/*
 * The high half of the time: as it was when `TIME_LOW` was last read, or as
 * last written, for a write of `TIME_LOW` to set.
 */
#define RTC_TIME_HIGH 0x004U

/*
 * The low half of the alarm's time. Writing it sets the alarm, with the high
 * half written to `ALARM_HIGH` before.
 */
#define RTC_ALARM_LOW 0x008U

/* The high half of the alarm's time. */
#define RTC_ALARM_HIGH 0x00CU

/* Whether the alarm, when it goes off, raises the interrupt. */
#define RTC_IRQ_ENABLED         0x010U
#define RTC_IRQ_ENABLED_ENABLED (1U << 0)

/* Writing anything takes the alarm off. */
#define RTC_CLEAR_ALARM 0x014U

/* Whether the alarm is set and has not gone off. */
#define RTC_ALARM_STATUS     0x018U
#define RTC_ALARM_STATUS_SET (1U << 0)

/* Writing anything clears the interrupt the alarm raised. */
#define RTC_CLEAR_INTERRUPT 0x01CU

#endif /* SOCPUPPET_REGS_RTC_H_ */
