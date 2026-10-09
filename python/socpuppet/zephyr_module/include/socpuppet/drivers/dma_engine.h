/*
 * The DMA engine of a socpuppet SSD: what copies between the host's
 * memory and the SSD's own.
 *
 * DMA is direct memory access: a device reading and writing memory by
 * itself. An NVMe drive is never handed data. A command says where in the
 * host's memory the data is, or is to go, and the drive goes there. The
 * firmware works out the addresses and this engine does the copying.
 */

#ifndef SOCPUPPET_DRIVERS_DMA_ENGINE_H_
#define SOCPUPPET_DRIVERS_DMA_ENGINE_H_

#include <stddef.h>
#include <stdint.h>

#include <zephyr/device.h>

/*
 * Copies `length` bytes from `host_address` in the host's memory to
 * `local`, in the SSD's own, and waits for it. A host's address is 64
 * bits wide even though the SSD's CPU is a 32-bit one.
 *
 * Returns 0, or -EIO if the copy was not made, or not all of it: nothing
 * answered at an address, on either side. What was copied before the
 * failure stays copied.
 */
int dma_engine_copy_from_host(const struct device *dev, uint64_t host_address, void *local,
			      size_t length);

/* The same, the other way: from `local` to `host_address`. */
int dma_engine_copy_to_host(const struct device *dev, uint64_t host_address, const void *local,
			    size_t length);

#endif /* SOCPUPPET_DRIVERS_DMA_ENGINE_H_ */
