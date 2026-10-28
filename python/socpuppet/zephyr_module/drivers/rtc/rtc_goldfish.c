/*
 * Zephyr's driver for the Goldfish real-time clock: the clock of Android's
 * emulator, which QEMU's `virt` machine has too, and which a socpuppet
 * host has on its IO die. Zephyr has no driver of its own for it; Linux's
 * is `rtc-goldfish`, and this one reads and writes the clock as that one
 * does. The registers are in <socpuppet/regs/rtc.h>, which is generated
 * from the clock's register map, and docs/models/rtc.md in socpuppet says
 * what they do.
 *
 * The clock counts nanoseconds since 1970 in 64 bits, read and written as
 * two 32-bit halves. A read of the low half keeps the high half as it was,
 * so the two cannot tear; a write of the low half sets the time, with the
 * high half written before it.
 *
 * It sets and gets the time only: the alarm is not offered.
 */

#define DT_DRV_COMPAT google_goldfish_rtc

#include <errno.h>
#include <stdint.h>
#include <time.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/rtc.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/sys/time_units.h>
#include <zephyr/sys/timeutil.h>

#include <socpuppet/regs/rtc.h>

struct rtc_goldfish_config {
	mem_addr_t base;
};

static int rtc_goldfish_set_time(const struct device *dev, const struct rtc_time *timeptr)
{
	const struct rtc_goldfish_config *config = dev->config;
	int64_t seconds;
	uint64_t time;

	if (timeptr == NULL) {
		return -EINVAL;
	}
	seconds = timeutil_timegm64((const struct tm *)timeptr);
	if (seconds < 0 || timeptr->tm_nsec < 0 || timeptr->tm_nsec >= NSEC_PER_SEC) {
		/* The clock counts from 1970 */
		return -EINVAL;
	}
	time = (uint64_t)seconds * NSEC_PER_SEC + (uint64_t)timeptr->tm_nsec;

	sys_write32((uint32_t)(time >> 32), config->base + RTC_TIME_HIGH);
	sys_write32((uint32_t)time, config->base + RTC_TIME_LOW);
	return 0;
}

static int rtc_goldfish_get_time(const struct device *dev, struct rtc_time *timeptr)
{
	const struct rtc_goldfish_config *config = dev->config;
	uint64_t low;
	uint64_t high;
	uint64_t time;
	time_t seconds;

	if (timeptr == NULL) {
		return -EINVAL;
	}
	low = sys_read32(config->base + RTC_TIME_LOW);
	high = sys_read32(config->base + RTC_TIME_HIGH);
	time = high << 32 | low;

	/* 64 bits of nanoseconds are some 584 years, which gmtime_r takes */
	seconds = (time_t)(time / NSEC_PER_SEC);
	gmtime_r(&seconds, rtc_time_to_tm(timeptr));
	timeptr->tm_nsec = (int)(time % NSEC_PER_SEC);
	/* The clock keeps no time zone, and so no daylight saving */
	timeptr->tm_isdst = -1;
	return 0;
}

static DEVICE_API(rtc, rtc_goldfish_api) = {
	.set_time = rtc_goldfish_set_time,
	.get_time = rtc_goldfish_get_time,
};

#define RTC_GOLDFISH_INIT(n)                                                                       \
	static const struct rtc_goldfish_config rtc_goldfish_config_##n = {                        \
		.base = DT_INST_REG_ADDR(n),                                                       \
	};                                                                                         \
	DEVICE_DT_INST_DEFINE(n, NULL, NULL, NULL, &rtc_goldfish_config_##n, POST_KERNEL,          \
			      CONFIG_RTC_INIT_PRIORITY, &rtc_goldfish_api);

DT_INST_FOREACH_STATUS_OKAY(RTC_GOLDFISH_INIT)
