/*
 * Zephyr's driver for the flash controller of a socpuppet SSD: what moves
 * a page between the NAND flash chip and the SSD's own memory. The
 * registers are in docs/models/flash-controller.md in socpuppet.
 *
 * It is a driver of Zephyr's flash class, so firmware uses the NAND
 * through flash_read(), flash_write() and flash_erase(), as it would any
 * flash. Three things about a NAND show through, as they do on real ones:
 *
 *   - A write is of whole NAND pages. The size of one is
 *     flash_get_write_block_size(), and an offset or a length that is not
 *     a multiple of it is refused.
 *   - An erase is of whole NAND blocks, which are what Zephyr's flash
 *     class calls pages: flash_get_page_info_by_offs() gives one.
 *   - The controller moves a page straight between the chip and memory,
 *     without the CPU touching a byte of it. So the buffer a caller gives
 *     is memory, and not, say, a register.
 *
 * A read may be of any bytes, as Zephyr asks of every flash driver. The
 * controller can only fetch a whole page, so a read of part of one is
 * fetched into a page of the driver's own and copied from there. A read
 * of whole pages goes straight to the caller's buffer, and that is the
 * kind to use for data. The driver has one such page and no lock on it:
 * one thread at a time.
 */

#define DT_DRV_COMPAT socpuppet_flash_controller

#include <errno.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/sys/util.h>

#include "command_status.h"

#define BLOCK           0x0C
#define PAGE            0x10
#define LOCAL_ADDRESS   0x14
#define PAGE_SIZE       0x20
#define PAGES_PER_BLOCK 0x24
#define BLOCKS          0x28

/* What the command register is told. */
#define READ_PAGE    1
#define PROGRAM_PAGE 2
#define ERASE_BLOCK  3
#define IDENTIFY     4

struct flash_controller_config {
	mm_reg_t base;
};

struct flash_controller_data {
	/* What the chip is, as it said when it was identified. */
	uint32_t page_size;
	uint32_t pages_per_block;
	uint32_t blocks;
	/* The same, as Zephyr's flash class wants it. */
	struct flash_parameters parameters;
	struct flash_pages_layout layout;
	/* A page of the chip, for a read that is not of whole pages. */
	uint8_t page[CONFIG_SOCPUPPET_FLASH_CONTROLLER_LARGEST_PAGE] __aligned(4);
};

static uint64_t flash_controller_bytes(const struct flash_controller_data *data)
{
	return (uint64_t)data->page_size * data->pages_per_block * data->blocks;
}

/* Whether a run of bytes is inside the chip. */
static bool flash_controller_has(const struct flash_controller_data *data, off_t offset,
				 size_t length)
{
	return offset >= 0 && (uint64_t)offset + length <= flash_controller_bytes(data);
}

/* Whether a run of bytes is whole units of `unit` bytes, inside the chip. */
static bool flash_controller_is_whole(const struct flash_controller_data *data, off_t offset,
				      size_t length, uint32_t unit)
{
	return flash_controller_has(data, offset, length) && offset % unit == 0 &&
	       length % unit == 0;
}

/* Has one page moved between the chip and the memory at `local`. */
static int flash_controller_move_page(const struct device *dev, uint32_t command, uint32_t page,
				      const void *local)
{
	const struct flash_controller_config *config = dev->config;
	const struct flash_controller_data *data = dev->data;

	sys_write32(page / data->pages_per_block, config->base + BLOCK);
	sys_write32(page % data->pages_per_block, config->base + PAGE);
	sys_write32((uint32_t)(uintptr_t)local, config->base + LOCAL_ADDRESS);

	return ssd_device_do(config->base, command);
}

static int flash_controller_read(const struct device *dev, off_t offset, void *buffer,
				 size_t length)
{
	struct flash_controller_data *data = dev->data;
	uint8_t *to = buffer;

	if (!flash_controller_has(data, offset, length)) {
		return -EINVAL;
	}

	while (length != 0) {
		uint32_t within = offset % data->page_size;
		size_t piece = MIN(length, data->page_size - within);
		/* A whole page goes straight to the caller, and a part by way of our own. */
		bool is_whole = piece == data->page_size;
		int result = flash_controller_move_page(dev, READ_PAGE, offset / data->page_size,
							is_whole ? to : data->page);

		if (result != 0) {
			return result;
		}
		if (!is_whole) {
			memcpy(to, &data->page[within], piece);
		}
		offset += piece;
		to += piece;
		length -= piece;
	}

	return 0;
}

static int flash_controller_write(const struct device *dev, off_t offset, const void *buffer,
				  size_t length)
{
	const struct flash_controller_data *data = dev->data;
	const uint8_t *from = buffer;

	if (!flash_controller_is_whole(data, offset, length, data->page_size)) {
		return -EINVAL;
	}

	for (uint32_t page = offset / data->page_size; length != 0; ++page) {
		int result = flash_controller_move_page(dev, PROGRAM_PAGE, page, from);

		if (result != 0) {
			return result;
		}
		from += data->page_size;
		length -= data->page_size;
	}

	return 0;
}

static int flash_controller_erase(const struct device *dev, off_t offset, size_t size)
{
	const struct flash_controller_config *config = dev->config;
	const struct flash_controller_data *data = dev->data;
	uint32_t block_size = data->page_size * data->pages_per_block;

	if (!flash_controller_is_whole(data, offset, size, block_size)) {
		return -EINVAL;
	}

	for (uint32_t block = offset / block_size; size != 0; size -= block_size, ++block) {
		int result;

		sys_write32(block, config->base + BLOCK);
		result = ssd_device_do(config->base, ERASE_BLOCK);
		if (result != 0) {
			return result;
		}
	}

	return 0;
}

static const struct flash_parameters *flash_controller_get_parameters(const struct device *dev)
{
	const struct flash_controller_data *data = dev->data;

	return &data->parameters;
}

static int flash_controller_get_size(const struct device *dev, uint64_t *size)
{
	*size = flash_controller_bytes(dev->data);

	return 0;
}

static void flash_controller_page_layout(const struct device *dev,
					 const struct flash_pages_layout **layout,
					 size_t *layout_size)
{
	const struct flash_controller_data *data = dev->data;

	*layout = &data->layout;
	*layout_size = 1;
}

static DEVICE_API(flash, flash_controller_api) = {
	.read = flash_controller_read,
	.write = flash_controller_write,
	.erase = flash_controller_erase,
	.get_parameters = flash_controller_get_parameters,
	.get_size = flash_controller_get_size,
	.page_layout = flash_controller_page_layout,
};

/*
 * The controller does not know what chip it has until it has been told to
 * ask, and cannot move a page before it knows how big one is.
 */
static int flash_controller_init(const struct device *dev)
{
	const struct flash_controller_config *config = dev->config;
	struct flash_controller_data *data = dev->data;

	if (ssd_device_do(config->base, IDENTIFY) != 0) {
		return -ENODEV;
	}

	data->page_size = sys_read32(config->base + PAGE_SIZE);
	data->pages_per_block = sys_read32(config->base + PAGES_PER_BLOCK);
	data->blocks = sys_read32(config->base + BLOCKS);
	/*
	 * An erased NAND cell holds a one. Zephyr declares a flash's write
	 * block size constant, for drivers that know it when they are built.
	 * This one learns it from the chip, so it fills the structure in by
	 * copying one over it (see docs/upstream.md in socpuppet).
	 */
	memcpy(&data->parameters,
	       &(const struct flash_parameters){
		       .write_block_size = data->page_size,
		       .erase_value = 0xFF,
	       },
	       sizeof(data->parameters));
	data->layout = (struct flash_pages_layout){
		.pages_count = data->blocks,
		.pages_size = data->page_size * data->pages_per_block,
	};

	return 0;
}

#define FLASH_CONTROLLER_DEFINE(n)                                                                 \
	static const struct flash_controller_config flash_controller_config##n = {                 \
		.base = DT_INST_REG_ADDR(n),                                                       \
	};                                                                                         \
	static struct flash_controller_data flash_controller_data##n;                              \
	DEVICE_DT_INST_DEFINE(n, flash_controller_init, NULL, &flash_controller_data##n,           \
			      &flash_controller_config##n, POST_KERNEL,                            \
			      CONFIG_FLASH_INIT_PRIORITY, &flash_controller_api);

DT_INST_FOREACH_STATUS_OKAY(FLASH_CONTROLLER_DEFINE)
