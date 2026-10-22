/* The flash translation layer. See ftl.h. */

#include "ftl.h"

#include <errno.h>
#include <stdbool.h>
#include <string.h>

#include <zephyr/drivers/flash.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

#include <socpuppet/regs/ftl_header.h>

#include "ssd.h"

/*
 * How much of a flash Zephyr's flash API has offsets for. An offset is an
 * off_t, which is signed, and 32 bits on a 32-bit CPU: 2 GiB, then. See
 * docs/upstream.md in socpuppet.
 */
#define FLASH_API_REACH (1ULL << (8 * sizeof(off_t) - 1))
#define MiB             (1ULL << 20)

/* In the table, a page of the drive that is in no NAND page. */
#define NOWHERE    UINT32_MAX
/* How many bytes an entry of the table takes. */
#define ENTRY_SIZE sizeof(uint32_t)

static uint32_t page_size;
/* How many pages the drive has: the NAND less the reserve. */
static uint32_t pages;
/* How many of the NAND's pages, at its start, are the reserve. */
static uint32_t reserve;
/*
 * How many bytes the table takes: whole pages, as on the NAND, from the
 * reserve's second page. The first is the header.
 */
static size_t table_bytes;
/*
 * For each page of the drive, the NAND page that holds it. The table is
 * whole pages, as it is on the NAND: the entries past the drive's last
 * page are NOWHERE.
 */
static uint32_t *where;
/* The next NAND page nobody has. */
static uint32_t next_free_nand_page;

/*
 * How many of the NAND's blocks, at its start, are the FTL's reserve,
 * where it keeps its table: the fewest whole blocks that hold a header
 * page and an entry for each of the NAND's pages. socpuppet.ftl in
 * socpuppet works it out the same way, and docs/models/ssd-firmware.md
 * says why.
 */
static uint32_t reserved_blocks(uint32_t nand_blocks, uint32_t pages_per_block,
				uint32_t nand_page_size)
{
	uint64_t needed = nand_page_size + (uint64_t)ENTRY_SIZE * pages_per_block * nand_blocks;
	uint64_t block_size = (uint64_t)pages_per_block * nand_page_size;

	return (uint32_t)((needed + block_size - 1) / block_size);
}

uint32_t ftl_pages(void)
{
	return pages;
}

uint32_t ftl_page_size(void)
{
	return page_size;
}

/*
 * Whether every page the table gives out is one the NAND has given: the
 * pages given out so far are the reserve's end up to the next free one,
 * which is at most the NAND's end. socpuppet.ftl's saved_table judges the
 * same way.
 */
static bool can_be_this_drives(void)
{
	if (next_free_nand_page < reserve || next_free_nand_page > reserve + pages) {
		return false;
	}
	for (uint32_t page = 0; page < pages; ++page) {
		if (where[page] != NOWHERE &&
		    (where[page] < reserve || where[page] >= next_free_nand_page)) {
			return false;
		}
	}

	return true;
}

/*
 * The table the reserve holds, if its header says it is this drive's and
 * the table can be; else an empty one, as on a NAND fresh from the
 * factory, whose erased header says nothing. If the NAND will not give up
 * the reserve, says so.
 */
static int load_the_table(void)
{
	uint8_t *header = ssd_page_buffer();
	int result = flash_read(ssd_nand, 0, header, page_size);
	bool this_drives = false;

	if (result == 0 && sys_get_le32(&header[FTL_HEADER_MAGIC]) == FTL_HEADER_MAGIC_NUMBER &&
	    sys_get_le32(&header[FTL_HEADER_VERSION]) == FTL_HEADER_VERSION_FIRST &&
	    sys_get_le32(&header[FTL_HEADER_PAGES]) == pages) {
		next_free_nand_page = sys_get_le32(&header[FTL_HEADER_NEXT_FREE]);
		result = flash_read(ssd_nand, page_size, where, table_bytes);
		this_drives = result == 0 && can_be_this_drives();
	}
	if (result == 0 && !this_drives) {
		for (size_t entry = 0; entry < table_bytes / ENTRY_SIZE; ++entry) {
			where[entry] = NOWHERE;
		}
		next_free_nand_page = reserve;
	}
	if (result != 0) {
		printk("The NAND would not give the FTL its reserve, where the table is kept "
		       "(%d).\n",
		       result);
	}

	return result;
}

int ftl_start(void)
{
	uint64_t bytes;
	size_t room;

	/*
	 * The NAND is written a page at a time and erased a block at a time,
	 * which Zephyr's flash API calls a page.
	 */
	struct flash_pages_info block;

	if (!device_is_ready(ssd_nand) || flash_get_size(ssd_nand, &bytes) != 0 ||
	    flash_get_page_info_by_offs(ssd_nand, 0, &block) != 0) {
		printk("The flash controller's driver did not start (it says why above), so there "
		       "is no NAND.\n");
		return -ENODEV;
	}
	/* Every page has to be somewhere flash_read() can be told to go. */
	if (bytes > FLASH_API_REACH) {
		printk("The NAND is %u MiB, and Zephyr's flash API reaches only the first %u MiB "
		       "of one on this CPU. Describe a smaller drive.\n",
		       (uint32_t)(bytes / MiB), (uint32_t)(FLASH_API_REACH / MiB));
		return -EFBIG;
	}
	page_size = flash_get_write_block_size(ssd_nand);
	uint32_t pages_per_block = block.size / page_size;
	uint32_t nand_blocks = bytes / block.size;
	/* The drive is the NAND's pages after the reserve. */
	reserve = reserved_blocks(nand_blocks, pages_per_block, page_size) * pages_per_block;
	pages = (nand_blocks * pages_per_block) - reserve;
	table_bytes = ROUND_UP((size_t)pages * ENTRY_SIZE, page_size);

	/*
	 * The table has what is left of the buffer, and has to fit. On this
	 * board it always does: a NAND the flash API can reach needs half of
	 * what there is. A board with a smaller buffer is what this is for.
	 */
	where = ssd_buffer_after_a_page(page_size, &room);
	if (room < table_bytes) {
		printk("A table for %u pages does not fit in what is left of the buffer, %u "
		       "bytes. Describe a smaller drive, or a bigger buffer.\n",
		       pages, (uint32_t)room);
		return -ENOMEM;
	}

	return load_the_table();
}

int ftl_save(void)
{
	/*
	 * The reserve is erased whole, the table programmed, and the header
	 * last: until the header is there, the reserve holds no table at all.
	 */
	int result = flash_erase(ssd_nand, 0, (size_t)reserve * page_size);

	if (result == 0) {
		result = flash_write(ssd_nand, page_size, where, table_bytes);
	}
	if (result == 0) {
		uint8_t *header = ssd_page_buffer();

		memset(header, 0xFF, page_size);
		sys_put_le32(FTL_HEADER_MAGIC_NUMBER, &header[FTL_HEADER_MAGIC]);
		sys_put_le32(FTL_HEADER_VERSION_FIRST, &header[FTL_HEADER_VERSION]);
		sys_put_le32(pages, &header[FTL_HEADER_PAGES]);
		sys_put_le32(next_free_nand_page, &header[FTL_HEADER_NEXT_FREE]);
		result = flash_write(ssd_nand, 0, header, page_size);
	}

	return result;
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
