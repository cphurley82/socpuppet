/*
 * The driver of the die-to-die link, on the IO die's manager: train the
 * link, let the other die go, train it again.
 *
 * A link is brought up once, so the suite does it once, in the order a
 * manager's firmware would, and writes down what it saw at each step. Each
 * case is about one of them.
 *
 * The other die is a stand-in here, the one `socpuppet run` puts there
 * (`one_round_trip` in socpuppet's boards/io_manager.py): once it is out
 * of reset it writes a word into this die's scratch memory, across the
 * link, and reads it back. That word arriving is how the suite knows the
 * other die really was let go.
 */

#include <errno.h>
#include <stdbool.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/reset.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/ztest.h>

#include <socpuppet/drivers/ucie_link.h>

/* Where the other die writes, and what: the stand-in's own word. */
#define SCRATCH        DT_REG_ADDR(DT_NODELABEL(io_scratch))
#define ITS_WORD       0xC0FFEE
/* Much longer than a write across a link that is up takes. */
#define LONG_ENOUGH_MS 20
/*
 * UCIe holds a link in reset for this long before training can begin, so
 * a link that is trained from the beginning is down for at least as long.
 */
#define RESET_HOLD_US  4000

static const struct device *const link = DEVICE_DT_GET_ONE(socpuppet_ucie_link);

static struct {
	bool up_before_training;
	int trained;
	bool up_once_trained;
	uint32_t scratch_before_the_release;
	int released;
	uint32_t scratch_after_the_release;
	int released_a_line_there_is_not;
	int retrained;
	uint32_t retraining_took_us;
	bool up_once_retrained;
} saw;

static void *bring_the_link_up_as_a_manager_does(void)
{
	uint32_t started;

	zassert_true(device_is_ready(link));

	saw.up_before_training = ucie_link_is_up(link);
	saw.trained = ucie_link_train(link);
	saw.up_once_trained = ucie_link_is_up(link);

	saw.scratch_before_the_release = sys_read32(SCRATCH);
	saw.released = reset_line_deassert(link, UCIE_LINK_THE_OTHER_DIE);
	k_msleep(LONG_ENOUGH_MS);
	saw.scratch_after_the_release = sys_read32(SCRATCH);

	saw.released_a_line_there_is_not = reset_line_deassert(link, UCIE_LINK_THE_OTHER_DIE + 1);

	started = k_cycle_get_32();
	saw.retrained = ucie_link_retrain(link);
	saw.retraining_took_us = k_cyc_to_us_floor32(k_cycle_get_32() - started);
	saw.up_once_retrained = ucie_link_is_up(link);

	return NULL;
}

ZTEST(ucie_link, test_a_link_that_has_not_been_trained_is_not_up)
{
	zassert_false(saw.up_before_training);
}

ZTEST(ucie_link, test_training_ends_with_the_link_up)
{
	zassert_ok(saw.trained);
	zassert_true(saw.up_once_trained);
}

ZTEST(ucie_link, test_the_other_die_does_nothing_until_it_is_let_go)
{
	zassert_not_equal(saw.scratch_before_the_release, ITS_WORD);
}

ZTEST(ucie_link, test_deasserting_the_links_reset_line_lets_the_other_die_run)
{
	zassert_ok(saw.released);
	zassert_equal(saw.scratch_after_the_release, ITS_WORD, "the scratch memory held 0x%x",
		      saw.scratch_after_the_release);
}

ZTEST(ucie_link, test_a_reset_line_other_than_the_other_die_is_refused)
{
	zassert_equal(saw.released_a_line_there_is_not, -EINVAL);
}

ZTEST(ucie_link, test_training_again_ends_with_the_link_up_again)
{
	zassert_ok(saw.retrained);
	zassert_true(saw.up_once_retrained);
}

ZTEST(ucie_link, test_training_again_starts_from_the_beginning)
{
	/*
	 * A link that is up and is asked only to train has nothing to do,
	 * and says so in microseconds. One that is told to start over goes
	 * down first, and is held in reset before it trains.
	 */
	zassert_true(saw.retraining_took_us >= RESET_HOLD_US, "it took %u us",
		     saw.retraining_took_us);
}

ZTEST_SUITE(ucie_link, NULL, bring_the_link_up_as_a_manager_does, NULL, NULL, NULL);
