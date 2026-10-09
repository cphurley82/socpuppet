/*
 * What a NAND adds to Zephyr's flash test, for the driver of the SSD's
 * flash controller: a write of more than one page, and what the driver
 * refuses because a NAND cannot do it.
 *
 * Zephyr's test (tests/drivers/flash/common in Zephyr) writes a page at a
 * time, and only what a flash can take.
 */

#include <errno.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/ztest.h>

/* The partition Zephyr's test uses, from the board's overlay. */
#define AREA storage_partition

/* Room for two NAND pages, of the biggest size the driver was built for. */
#define TWO_PAGES (2 * CONFIG_SOCPUPPET_FLASH_CONTROLLER_LARGEST_PAGE)

static const struct device *const nand = PARTITION_DEVICE(AREA);
/*
 * The NAND block these tests write in: the partition's third. Zephyr's
 * test has the first two.
 */
static struct flash_pages_info block;
static size_t page_size;
static uint8_t written[TWO_PAGES];
static uint8_t read_back[TWO_PAGES];

static void *nand_setup(void)
{
	struct flash_pages_info first;

	zassert_true(device_is_ready(nand));
	page_size = flash_get_write_block_size(nand);
	zassert_true(2 * page_size <= TWO_PAGES);
	zassert_ok(flash_get_page_info_by_offs(nand, PARTITION_OFFSET(AREA), &first));
	zassert_ok(flash_get_page_info_by_idx(nand, first.index + 2, &block));
	/* No two neighbours the same, and the two pages not alike. */
	for (size_t at = 0; at < TWO_PAGES; ++at) {
		written[at] = (uint8_t)(at * 7 + at / page_size);
	}

	return NULL;
}

static void nand_before(void *fixture)
{
	ARG_UNUSED(fixture);

	zassert_ok(flash_erase(nand, block.start_offset, block.size));
}

ZTEST(nand, test_a_write_of_two_pages_reads_back_in_one_read)
{
	/* Not at the start of the block, so that a page number matters. */
	off_t at = block.start_offset + page_size;

	zassert_ok(flash_write(nand, at, written, 2 * page_size));

	zassert_ok(flash_read(nand, at, read_back, 2 * page_size));
	zassert_mem_equal(read_back, written, 2 * page_size);
}

ZTEST(nand, test_a_write_that_is_not_of_whole_pages_is_refused_and_writes_nothing)
{
	zassert_equal(flash_write(nand, block.start_offset, written, page_size / 2), -EINVAL);
	zassert_equal(flash_write(nand, block.start_offset + 1, written, page_size), -EINVAL);

	/* An erased NAND reads as all ones. */
	zassert_ok(flash_read(nand, block.start_offset, read_back, 2 * page_size));
	for (size_t at = 0; at < 2 * page_size; ++at) {
		zassert_equal(read_back[at], 0xFF, "byte %zu was written", at);
	}
}

ZTEST(nand, test_an_erase_that_is_not_of_whole_blocks_is_refused_and_erases_nothing)
{
	zassert_ok(flash_write(nand, block.start_offset, written, page_size));

	zassert_equal(flash_erase(nand, block.start_offset, block.size / 2), -EINVAL);
	zassert_equal(flash_erase(nand, block.start_offset + page_size, block.size), -EINVAL);

	zassert_ok(flash_read(nand, block.start_offset, read_back, page_size));
	zassert_mem_equal(read_back, written, page_size);
}

ZTEST(nand, test_a_read_that_runs_past_the_end_of_the_nand_is_refused)
{
	uint64_t size;

	zassert_ok(flash_get_size(nand, &size));

	zassert_equal(flash_read(nand, (off_t)size - 1, read_back, 2), -EINVAL);
}

ZTEST_SUITE(nand, NULL, nand_setup, nand_before, NULL, NULL);
