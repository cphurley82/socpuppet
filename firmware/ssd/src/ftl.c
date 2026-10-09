/* The flash translation layer. See ftl.h. */

#include "ftl.h"

#include <errno.h>
#include <string.h>

#include <zephyr/drivers/flash.h>
#include <zephyr/sys/printk.h>

#include "ssd.h"

/*
 * How much of a flash Zephyr's flash API has offsets for. An offset is an
 * off_t, which is signed, and 32 bits on a 32-bit CPU: 2 GiB, then. See
 * docs/upstream.md in socpuppet.
 */
#define FLASH_API_REACH (1ULL << (8 * sizeof(off_t) - 1))
#define MiB             (1ULL << 20)

/* In the table, a page of the drive that is in no NAND page. */
#define NOWHERE UINT32_MAX

static uint32_t page_size;
static uint32_t pages;
/* For each page of the drive, the NAND page that holds it. */
static uint32_t *where;
/* The next NAND page nobody has. */
static uint32_t next_free_nand_page;

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
	size_t room;
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
	/* Every page has to be somewhere flash_read() can be told to go. */
	if (bytes > FLASH_API_REACH) {
		printk("The NAND is %u MiB, and Zephyr's flash API reaches only the first %u MiB "
		       "of one on this CPU. Describe a smaller drive.\n",
		       (uint32_t)(bytes / MiB), (uint32_t)(FLASH_API_REACH / MiB));
		return -EFBIG;
	}
	pages = bytes / page_size;

	/* The table has what is left of the buffer, and has to fit. */
	where = ssd_buffer_after_a_page(page_size, &room);
	if (room / sizeof(*where) < pages) {
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
