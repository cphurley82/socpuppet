/*
 * What the DMA engine and the flash controller of a socpuppet SSD have in
 * common: a command register, and a status register that says busy until
 * the command has been carried out, and then done or error.
 */

#ifndef SOCPUPPET_DRIVERS_SSD_COMMAND_STATUS_H_
#define SOCPUPPET_DRIVERS_SSD_COMMAND_STATUS_H_

#include <errno.h>
#include <stdint.h>

#include <zephyr/arch/cpu.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/sys/util.h>

#define SSD_DEVICE_COMMAND 0x00
#define SSD_DEVICE_STATUS  0x04

#define SSD_DEVICE_ERROR BIT(1)
#define SSD_DEVICE_BUSY  BIT(2)

/*
 * Gives the device at `base` a command and waits for it. Returns 0, or
 * -EIO if the device says the command was not carried out.
 *
 * The device does its work alongside the CPU and says it is busy
 * meanwhile, so the driver asks until it is not. Nothing takes simulated
 * time yet, and the answer comes at the first or second time of asking.
 * The device has an interrupt for when asking would take too long.
 */
static inline int ssd_device_do(mm_reg_t base, uint32_t command)
{
	uint32_t status;

	sys_write32(command, base + SSD_DEVICE_COMMAND);
	do {
		status = sys_read32(base + SSD_DEVICE_STATUS);
	} while ((status & SSD_DEVICE_BUSY) != 0);

	return (status & SSD_DEVICE_ERROR) != 0 ? -EIO : 0;
}

#endif /* SOCPUPPET_DRIVERS_SSD_COMMAND_STATUS_H_ */
