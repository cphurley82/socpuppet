/* The flash translation layer. See ftl.h. */

#include "ftl.h"

#include <errno.h>
#include <string.h>

#include <zephyr/devicetree.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/sys/util.h>

#include "ssd.h"

/*
 * The buffer, from the board's devicetree. The firmware carves it up by
 * hand: a page of the drive, a page of scratch, and the table.
 */
#define BUFFER      DT_NODELABEL(ssd_buffer)
#define BUFFER_BASE ((uint8_t *)DT_REG_ADDR(BUFFER))
#define BUFFER_SIZE DT_REG_SIZE(BUFFER)

/* In the table, a page of the drive that is in no NAND page. */
#define NOWHERE UINT32_MAX

static uint32_t page_size;
static uint32_t pages;
/* For each page of the drive, the NAND page that holds it. */
static uint32_t *where;
/* The next NAND page nobody has. */
static uint32_t next_free_nand_page;

uint8_t *ssd_page_buffer(void)
{
	return BUFFER_BASE;
}

uint8_t *ssd_scratch(void)
{
	return BUFFER_BASE + ROUND_UP(page_size, NVME_HOST_PAGE);
}

uint32_t ftl_pages(void)
{
	return pages;
}

uint32_t ftl_page_size(void)
{
	return page_size;
}

int ftl_start(void)
{
	uint64_t bytes;
	int result;

	if (!device_is_ready(ssd_nand)) {
		return -ENODEV;
	}
	/* The NAND is written a page at a time. */
	page_size = flash_get_write_block_size(ssd_nand);
	result = flash_get_size(ssd_nand, &bytes);
	if (result != 0) {
		return result;
	}
	if (page_size == 0 || page_size % NVME_BLOCK_SIZE != 0) {
		return -ENOTSUP;
	}
	pages = bytes / page_size;

	/* The table goes after the two pages, and has to fit. */
	where = (uint32_t *)(ssd_scratch() + NVME_HOST_PAGE);
	if ((uint8_t *)(where + pages) > BUFFER_BASE + BUFFER_SIZE) {
		return -ENOMEM;
	}
	for (uint32_t page = 0; page < pages; ++page) {
		where[page] = NOWHERE;
	}
	next_free_nand_page = 0;

	return 0;
}

int ftl_load(uint32_t page)
{
	if (where[page] == NOWHERE) {
		memset(ssd_page_buffer(), 0, page_size);
		return 0;
	}

	return flash_read(ssd_nand, (off_t)where[page] * page_size, ssd_page_buffer(), page_size);
}

int ftl_store(uint32_t page)
{
	uint32_t nand_page = where[page] == NOWHERE ? next_free_nand_page : where[page];
	int result =
		flash_write(ssd_nand, (off_t)nand_page * page_size, ssd_page_buffer(), page_size);

	/* The table says so only once it is true. */
	if (result == 0 && where[page] == NOWHERE) {
		where[page] = nand_page;
		++next_free_nand_page;
	}

	return result;
}
