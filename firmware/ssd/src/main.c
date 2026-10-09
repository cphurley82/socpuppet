/*
 * The firmware of socpuppet's SSD.
 *
 * The SSD's hardware keeps the host's queues and moves the data, and the
 * firmware makes the decisions. What it does, for ever:
 *
 *   1. Wait for the NVMe frontend to say something has happened.
 *   2. If the host has reset or enabled the controller, see to that.
 *   3. If a command is waiting, read it, do what it says, and have the
 *      frontend post how it went.
 *
 * python/socpuppet/ssd_firmware.py in socpuppet is the same firmware as a
 * Python script, which stands in for this one where there is no CPU.
 */

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

#include <socpuppet/drivers/nvme_frontend.h>

#include "ftl.h"
#include "ssd.h"

const struct device *const ssd_frontend = DEVICE_DT_GET_ONE(socpuppet_nvme_frontend);
const struct device *const ssd_dma = DEVICE_DT_GET_ONE(socpuppet_dma_engine);
const struct device *const ssd_nand = DEVICE_DT_GET_ONE(socpuppet_flash_controller);

BUILD_ASSERT(sizeof(struct nvme_command) == NVME_FRONTEND_COMMAND_SIZE,
	     "What the frontend hands over is one whole NVMe command.");

static void deal_with_the_command(void)
{
	struct nvme_command command;
	uint16_t from_queue = nvme_frontend_read_command(ssd_frontend, command.bytes);
	/*
	 * Queue 0 is the admin queue. The same opcode means one thing there
	 * and another on an I/O queue.
	 */
	struct nvme_outcome outcome =
		from_queue == 0 ? admin_command(&command) : io_command(&command);

	nvme_frontend_post(ssd_frontend, outcome.status, outcome.result);
}

int main(void)
{
	int result = ftl_start();

	if (result != 0) {
		printk("The SSD's firmware cannot use its NAND (error %d), and stops.\n", result);
		return 0;
	}
	admin_start();
	printk("socpuppet SSD firmware: a drive of %u pages of %u bytes\n", ftl_pages(),
	       ftl_page_size());

	for (;;) {
		uint32_t happened = nvme_frontend_wait(ssd_frontend);

		/*
		 * The reset first: what the host enabled is the controller as
		 * it is after it. The queues are gone, and what is on the
		 * drive stays. The acknowledgement comes last, because it
		 * says the firmware has let go of everything from before.
		 */
		if ((happened & NVME_FRONTEND_RESET) != 0) {
			admin_forget_the_queues();
			nvme_frontend_acknowledge(ssd_frontend, NVME_FRONTEND_RESET);
		}
		/*
		 * There is nothing to start up, so the firmware is ready at
		 * once. If the host has changed its mind again by now, the
		 * frontend does not hear this, and says so in its own time.
		 */
		if ((happened & NVME_FRONTEND_ENABLED) != 0) {
			nvme_frontend_acknowledge(ssd_frontend, NVME_FRONTEND_ENABLED);
			nvme_frontend_say_ready(ssd_frontend);
		}
		if ((happened & NVME_FRONTEND_COMMAND_WAITING) != 0) {
			deal_with_the_command();
		}
	}

	return 0;
}
