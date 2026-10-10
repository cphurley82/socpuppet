/*
 * The firmware of socpuppet's IO-die manager.
 *
 * A chiplet host is one chip built from two dies, and when the power
 * comes on the link between them is not there. This is the firmware that
 * brings it up: it trains the link, and then lets the compute die out of
 * reset, which is the whole reason the IO die has a CPU of its own.
 *
 * Everything it does is three calls. The link is a device in the
 * devicetree, its training is in <socpuppet/drivers/ucie_link.h>, and
 * letting the other die go is Zephyr's reset API, because that is what it
 * is: the other die is this link's one reset line.
 */

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/reset.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

#include <socpuppet/drivers/ucie_link.h>

/* The one link this die has. A board without one does not build. */
static const struct device *const link = DEVICE_DT_GET_ONE(socpuppet_ucie_link);

int main(void)
{
	int failed;

	printk("iomgr: training the D2D link\n");
	failed = ucie_link_train(link);
	if (failed != 0) {
		printk("iomgr: the D2D link would not train (%d)\n", failed);
		return 0;
	}
	printk("iomgr: D2D link up\n");

	failed = reset_line_deassert(link, UCIE_LINK_THE_OTHER_DIE);
	if (failed != 0) {
		printk("iomgr: the compute die would not come out of reset (%d)\n", failed);
		return 0;
	}
	printk("iomgr: compute die released\n");

	/*
	 * The compute die is running now, and the manager's work is to keep
	 * the link up under it. It sleeps until the link says it has gone
	 * down, and trains it again. What crossed while it was down was
	 * refused: on real hardware the other die would see bus faults.
	 */
	for (;;) {
		ucie_link_wait_until_down(link);
		printk("iomgr: the D2D link went down\n");
		if (ucie_link_retrain(link) != 0) {
			printk("iomgr: the D2D link would not train again\n");
			return 0;
		}
		printk("iomgr: D2D link up\n");
	}

	return 0;
}
