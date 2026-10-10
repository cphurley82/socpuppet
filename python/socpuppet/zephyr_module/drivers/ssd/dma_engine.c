/*
 * Zephyr's driver for the DMA engine of a socpuppet SSD. The registers are
 * in <socpuppet/regs/dma_engine.h>, which is generated from the engine's
 * register map, and docs/models/dma-engine.md in socpuppet says what they
 * do.
 *
 * Zephyr has a DMA driver class of its own, for controllers with channels
 * that a peripheral's driver sets up and leaves running. This engine makes
 * one copy when told and has nothing to set up, and one end of the copy is
 * in another machine's memory, at a 64-bit address. So it has two
 * functions of its own.
 */

#define DT_DRV_COMPAT socpuppet_dma_engine

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/sys/sys_io.h>

#include <socpuppet/drivers/dma_engine.h>
#include <socpuppet/regs/dma_engine.h>

#include "command_status.h"

struct dma_engine_config {
	mm_reg_t base;
};

static int dma_engine_copy(const struct device *dev, uint32_t direction, uint64_t host_address,
			   const void *local, size_t length)
{
	const struct dma_engine_config *config = dev->config;

	sys_write32((uint32_t)host_address, config->base + DMA_ENGINE_HOST_ADDRESS_LOW);
	sys_write32((uint32_t)(host_address >> 32), config->base + DMA_ENGINE_HOST_ADDRESS_HIGH);
	sys_write32((uint32_t)(uintptr_t)local, config->base + DMA_ENGINE_LOCAL_ADDRESS);
	sys_write32((uint32_t)length, config->base + DMA_ENGINE_LENGTH);

	return ssd_device_do(config->base, direction);
}

int dma_engine_copy_from_host(const struct device *dev, uint64_t host_address, void *local,
			      size_t length)
{
	return dma_engine_copy(dev, DMA_ENGINE_COMMAND_FROM_HOST, host_address, local, length);
}

int dma_engine_copy_to_host(const struct device *dev, uint64_t host_address, const void *local,
			    size_t length)
{
	return dma_engine_copy(dev, DMA_ENGINE_COMMAND_TO_HOST, host_address, local, length);
}

#define DMA_ENGINE_DEFINE(n)                                                                       \
	static const struct dma_engine_config dma_engine_config##n = {                             \
		.base = DT_INST_REG_ADDR(n),                                                       \
	};                                                                                         \
	DEVICE_DT_INST_DEFINE(n, NULL, NULL, NULL, &dma_engine_config##n, POST_KERNEL,             \
			      CONFIG_KERNEL_INIT_PRIORITY_DEVICE, NULL);

DT_INST_FOREACH_STATUS_OKAY(DMA_ENGINE_DEFINE)
