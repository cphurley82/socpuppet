/*
 * A firmware that is reset twice, and says why each time it starts.
 *
 * Every socpuppet CPU has a system controller, which says why the CPU was
 * last reset, and a watchdog, which resets it when firmware stops feeding
 * it. This uses both, through Zephyr's own drivers, and nothing else:
 *
 *   1. From power-on, it has the watchdog interrupt when it runs out, and
 *      not reset, waits to be interrupted, and then asks for a reset
 *      (sys_reboot).
 *   2. Reset by its own asking, it has the watchdog reset when it runs
 *      out, feeds it for twice as long as that takes, and then stops
 *      feeding and waits.
 *   3. Reset by the watchdog, it says so and is done.
 *
 * What was in memory is gone at each reset: what tells the three starts
 * apart is the system controller's register, and nothing the firmware
 * kept.
 */
#include <zephyr/device.h>
#include <zephyr/drivers/syscon.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/reboot.h>

#include <socpuppet/regs/system_controller.h>

/*
 * How long the watchdog gives firmware between feeds, how often this feeds
 * it, and how many times: for two periods, so that a watchdog which took
 * no notice of a feed would have bitten long before the last one.
 */
#define PERIOD_MS     90
#define FEED_EVERY_MS 30
#define FEEDS         6

static const struct device *const system_controller =
	DEVICE_DT_GET_ONE(socpuppet_system_controller);
static const struct device *const watchdog = DEVICE_DT_GET_ONE(sifive_wdt);

static const char *name_of(uint32_t cause)
{
	switch (cause) {
	case SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON:
		return "power-on";
	case SYSTEM_CONTROLLER_RESET_CAUSE_WATCHDOG:
		return "watchdog";
	case SYSTEM_CONTROLLER_RESET_CAUSE_SOFTWARE:
		return "software";
	default:
		return "unknown";
	}
}

/*
 * Starts the watchdog, to run out `ms` after it was last fed. Returns the
 * channel to feed, or a negative number, having said so, if it would not
 * start.
 */
static int start_watchdog(uint32_t ms, uint8_t flags, wdt_callback_t callback)
{
	const struct wdt_timeout_cfg timeout = {
		.window.max = ms,
		.flags = flags,
		.callback = callback,
	};
	int channel = wdt_install_timeout(watchdog, &timeout);
	int failed = channel < 0 ? channel : wdt_setup(watchdog, 0);

	if (failed < 0) {
		printk("watchdog: it would not start (%d)\n", failed);
		return failed;
	}
	return channel;
}

/* Given by the watchdog's interrupt, when it has run out. */
static K_SEM_DEFINE(ran_out, 0, 1);

static void it_ran_out(const struct device *dev, int channel)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(channel);

	k_sem_give(&ran_out);
}

/*
 * Has the watchdog interrupt when it runs out, and waits for that. The
 * interrupt is a wire to an interrupt controller on the watchdog's own
 * die, and reaches the CPU from there. It runs out as soon as this would
 * next have fed it, and is given three times that long to say so.
 */
static void run_out_and_be_told(void)
{
	if (start_watchdog(FEED_EVERY_MS, WDT_FLAG_RESET_NONE, it_ran_out) < 0) {
		return;
	}
	if (k_sem_take(&ran_out, K_MSEC(PERIOD_MS)) == 0) {
		printk("watchdog: ran out, and interrupted\n");
	} else {
		printk("watchdog: no interrupt came\n");
	}
}

/* Starts the watchdog, feeds it for a while, and then lets it run out. */
static void feed_and_then_stop(void)
{
	int channel = start_watchdog(PERIOD_MS, WDT_FLAG_RESET_SOC, NULL);

	if (channel < 0) {
		return;
	}
	for (int fed = 1; fed <= FEEDS; fed++) {
		k_msleep(FEED_EVERY_MS);
		wdt_feed(watchdog, channel);
		printk("watchdog: fed %d\n", fed);
	}
	printk("watchdog: no more feeding\n");
	k_sleep(K_FOREVER);
}

int main(void)
{
	uint32_t cause;
	int failed = syscon_read_reg(system_controller, SYSTEM_CONTROLLER_RESET_CAUSE, &cause);

	if (failed != 0) {
		printk("reset cause: the system controller would not say (%d)\n", failed);
		return 0;
	}
	printk("reset cause: %s\n", name_of(cause));

	switch (cause) {
	case SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON:
		run_out_and_be_told();
		sys_reboot(SYS_REBOOT_COLD);
		break;
	case SYSTEM_CONTROLLER_RESET_CAUSE_SOFTWARE:
		feed_and_then_stop();
		break;
	case SYSTEM_CONTROLLER_RESET_CAUSE_WATCHDOG:
		/* The watchdog bit, and that is the end of the story. */
		break;
	default:
		break;
	}
	return 0;
}
