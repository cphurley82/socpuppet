/* The system controller through Zephyr's syscon API, from inside Zephyr. */
#include <socpuppet/regs/system_controller.h>
#include <zephyr/device.h>
#include <zephyr/drivers/syscon.h>
#include <zephyr/ztest.h>

static const struct device* const syscon =
    DEVICE_DT_GET_ONE(socpuppet_system_controller);

ZTEST(syscon_reset_cause, test_the_first_start_is_a_power_on) {
  uint32_t cause = 0xFFFFFFFF;

  zassert_true(device_is_ready(syscon));
  zassert_ok(syscon_read_reg(syscon, SYSTEM_CONTROLLER_RESET_CAUSE, &cause));
  zassert_equal(cause, SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON, "cause was %u",
                cause);
}

ZTEST(syscon_reset_cause, test_the_size_is_the_register_maps) {
  size_t size;

  zassert_ok(syscon_get_size(syscon, &size));
  zassert_equal(size, SYSTEM_CONTROLLER_SIZE);
}

ZTEST_SUITE(syscon_reset_cause, NULL, NULL, NULL, NULL, NULL);
