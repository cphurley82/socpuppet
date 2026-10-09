/*
 * The SSD's hardware, as its firmware reaches it, and the parts of the
 * firmware as they call each other.
 */

#ifndef FIRMWARE_SSD_SSD_H_
#define FIRMWARE_SSD_SSD_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <socpuppet/drivers/nvme_frontend.h>
#include <zephyr/device.h>

#include "nvme.h"

/*
 * The three devices: the NVMe frontend, which keeps the host's queues, the
 * DMA engine, which copies to and from the host's memory, and the NAND,
 * through its flash controller.
 */
extern const struct device *const ssd_frontend;
extern const struct device *const ssd_dma;
extern const struct device *const ssd_nand;

/*
 * The buffer: the SSD's own memory that data passes through on its way
 * between the host and the NAND. The firmware keeps three things in it,
 * in this order (buffer.c).
 */
/*
 * A page of scratch, for what the firmware makes up to send to the host,
 * and for what it fetches from the host to read. It is one page of the
 * host's memory long.
 */
uint8_t *ssd_scratch(void);
/*
 * One page of the drive, as it is being read or written. How long it is
 * depends on the NAND.
 */
uint8_t *ssd_page_buffer(void);
/*
 * What is left after a page of the drive of `page_size` bytes: where it
 * starts, and in `size` how many bytes there are, which is none if the
 * page did not fit. The flash translation layer keeps its table here.
 */
void *ssd_buffer_after_a_page(uint32_t page_size, size_t *size);

/* admin.c: the commands that manage the controller. */
/* Asks the frontend what it has, once, before the first command. */
void admin_start(void);
struct nvme_outcome admin_command(const struct nvme_command *command);
/* The host has reset the controller: the I/O queues are gone. */
void admin_forget_the_queues(void);

/* io.c: the commands that read and write the drive. */
struct nvme_outcome io_command(const struct nvme_command *command);
/* How many blocks the drive has, as the host counts them. */
uint64_t io_drive_blocks(void);

#endif /* FIRMWARE_SSD_SSD_H_ */
