/*
 * The system controller, as Zephyr's own syscon driver reads it.
 *
 * There is no driver of socpuppet's here: the block is described in the
 * devicetree as a `syscon`, and Zephyr's driver for any such block of
 * registers does the reading. What is tested is that the devicetree, the
 * generated register names and the model agree.
 */

#include <stddef.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/drivers/syscon.h>
#include <zephyr/ztest.h>

#include <socpuppet/regs/system_controller.h>

static const struct device *const syscon = DEVICE_DT_GET_ONE(socpuppet_system_controller);

ZTEST(syscon_reset_cause, test_a_cpu_that_has_only_been_powered_on_reads_that_as_the_cause)
{
	uint32_t cause = UINT32_MAX;

	zassert_true(device_is_ready(syscon));
	zassert_ok(syscon_read_reg(syscon, SYSTEM_CONTROLLER_RESET_CAUSE, &cause));
	zassert_equal(cause, SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON, "the cause was %u", cause);
}

ZTEST(syscon_reset_cause, test_the_block_is_as_big_as_its_register_map)
{
	size_t size = 0;

	zassert_ok(syscon_get_size(syscon, &size));
	zassert_equal(size, SYSTEM_CONTROLLER_SIZE, "the size was %zu", size);
}

ZTEST_SUITE(syscon_reset_cause, NULL, NULL, NULL, NULL, NULL);
