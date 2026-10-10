/*
 * What the DMA engine and the flash controller of a socpuppet SSD have in
 * common: a command register, and a status register that says busy until
 * the command has been carried out, and then done or error.
 *
 * The registers are a command device's, <socpuppet/regs/command_device.h>,
 * which both devices begin with. docs/models/command-device.md in
 * socpuppet says what they do.
 */

#ifndef SOCPUPPET_DRIVERS_SSD_COMMAND_STATUS_H_
#define SOCPUPPET_DRIVERS_SSD_COMMAND_STATUS_H_

#include <errno.h>
#include <stdint.h>

#include <zephyr/arch/cpu.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/sys/util.h>

#include <socpuppet/regs/command_device.h>

/*
 * How long a device is given to carry a command out, in microseconds: a
 * tenth of a second. A device that is still busy after that is broken.
 */
#define SSD_DEVICE_PATIENCE 100000

/*
 * Gives the device at `base` a command and waits for it. Returns 0, -EIO
 * if the device says the command was not carried out, or -ETIMEDOUT if it
 * never said either.
 *
 * The device does its work alongside the CPU and says it is busy
 * meanwhile, so the driver asks until it is not. Nothing takes simulated
 * time yet, and the answer comes at the first time of asking. The device
 * has an interrupt for when asking would take too long.
 */
static inline int ssd_device_do(mm_reg_t base, uint32_t command)
{
	uint32_t status;

	sys_write32(command, base + COMMAND_DEVICE_COMMAND);
	if (!WAIT_FOR(((status = sys_read32(base + COMMAND_DEVICE_STATUS)) &
		       COMMAND_DEVICE_STATUS_BUSY) == 0,
		      SSD_DEVICE_PATIENCE,
		      /* ask again at once */)) {
		return -ETIMEDOUT;
	}

	return (status & COMMAND_DEVICE_STATUS_ERROR) != 0 ? -EIO : 0;
}

#endif /* SOCPUPPET_DRIVERS_SSD_COMMAND_STATUS_H_ */
