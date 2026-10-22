/*
 * The flash translation layer of the SSD's firmware (../../src/ftl.c), a
 * call at a time: what a page of the drive reads as before and after it is
 * written, and where in the NAND it is kept.
 *
 * The test is the firmware here. It has the firmware's own ftl.c and
 * buffer.c in it, and the NAND through the same driver.
 */

#include <stdbool.h>
#include <stdint.h>
#include <sys/types.h>

#include <zephyr/device.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/ztest.h>

#include "ftl.h"
#include "ssd.h"

/* The firmware's main.c says which device is the NAND. Here this does. */
const struct device *const ssd_nand = DEVICE_DT_GET_ONE(socpuppet_flash_controller);

/* A page of the drive that is not the first. Its last page is another. */
#define A_PAGE 7

static uint32_t the_last_page(void)
{
	return ftl_pages() - 1;
}

/* Fills the page buffer with bytes that say which filling it was. */
static void fill_the_page_buffer(uint8_t with)
{
	uint8_t *page = ssd_page_buffer();

	for (uint32_t at = 0; at < ftl_page_size(); ++at) {
		page[at] = (uint8_t)(with + at * 7);
	}
}

/* Whether the page buffer holds what `fill_the_page_buffer(with)` put there. */
static bool the_page_buffer_holds(uint8_t with)
{
	const uint8_t *page = ssd_page_buffer();

	for (uint32_t at = 0; at < ftl_page_size(); ++at) {
		if (page[at] != (uint8_t)(with + at * 7)) {
			return false;
		}
	}

	return true;
}

static bool the_page_buffer_is_all_zeros(void)
{
	const uint8_t *page = ssd_page_buffer();

	for (uint32_t at = 0; at < ftl_page_size(); ++at) {
		if (page[at] != 0) {
			return false;
		}
	}

	return true;
}

/*
 * How many of the NAND's pages, at its start, are the FTL's reserve: the
 * fewest whole blocks that hold a header page and four bytes for each of
 * the NAND's pages (docs/models/ssd-firmware.md in socpuppet).
 */
static uint32_t reserved_pages(void)
{
	struct flash_pages_info block;
	uint64_t bytes;

	zassert_ok(flash_get_page_info_by_offs(ssd_nand, 0, &block));
	zassert_ok(flash_get_size(ssd_nand, &bytes));
	uint64_t needed = ftl_page_size() + 4 * (bytes / ftl_page_size());

	return (uint32_t)((needed + block.size - 1) / block.size) * (block.size / ftl_page_size());
}

/* Whether a page of the NAND itself, counted from zero, holds that filling. */
static bool the_nand_page_holds(uint32_t nand_page, uint8_t with)
{
	zassert_ok(flash_read(ssd_nand, (off_t)nand_page * ftl_page_size(), ssd_page_buffer(),
			      ftl_page_size()));

	return the_page_buffer_holds(with);
}

/*
 * The table is emptied before each case, and the NAND is not: it keeps
 * what the cases before left in it, which an ideal NAND lets the next one
 * program over. So each case stores fillings of its own, which no other
 * case could have left where it looks.
 */
static void start_with_an_empty_table(void *fixture)
{
	ARG_UNUSED(fixture);

	zassert_ok(ftl_start());
	zassert_true(ftl_pages() > A_PAGE + 1);
}

ZTEST(ftl, test_the_drive_is_the_nand_less_its_reserve_in_pages_of_the_nands_size)
{
	uint64_t bytes;

	zassert_ok(flash_get_size(ssd_nand, &bytes));

	zassert_equal(ftl_page_size(), flash_get_write_block_size(ssd_nand));
	zassert_equal(ftl_pages() + reserved_pages(), bytes / ftl_page_size());
}

ZTEST(ftl, test_a_page_that_was_never_written_loads_as_zeros)
{
	fill_the_page_buffer(0x5A);

	zassert_ok(ftl_load(A_PAGE));

	zassert_true(the_page_buffer_is_all_zeros());
}

ZTEST(ftl, test_a_page_that_was_stored_loads_as_it_was_stored)
{
	fill_the_page_buffer(0x11);
	zassert_ok(ftl_store(A_PAGE));
	fill_the_page_buffer(0xEE);

	zassert_ok(ftl_load(A_PAGE));

	zassert_true(the_page_buffer_holds(0x11));
}

ZTEST(ftl, test_a_page_stored_a_second_time_loads_as_the_second)
{
	fill_the_page_buffer(0x21);
	zassert_ok(ftl_store(A_PAGE));
	fill_the_page_buffer(0x22);
	zassert_ok(ftl_store(A_PAGE));
	fill_the_page_buffer(0xEE);

	zassert_ok(ftl_load(A_PAGE));

	zassert_true(the_page_buffer_holds(0x22));
}

ZTEST(ftl, test_storing_one_page_leaves_another_as_it_was)
{
	fill_the_page_buffer(0x31);
	zassert_ok(ftl_store(A_PAGE));
	fill_the_page_buffer(0x32);
	zassert_ok(ftl_store(the_last_page()));

	zassert_ok(ftl_load(A_PAGE));

	zassert_true(the_page_buffer_holds(0x31));
}

ZTEST(ftl, test_a_page_stored_again_does_not_take_another_page_of_the_nand)
{
	/*
	 * The first page of the drive to be stored is in the first NAND page
	 * after the reserve and the next one in the page after that,
	 * wherever in the drive they are. A page stored again stays where it
	 * is, so the next new one still gets the second page after the
	 * reserve.
	 */
	fill_the_page_buffer(0x41);
	zassert_ok(ftl_store(A_PAGE));
	zassert_ok(ftl_store(A_PAGE));
	fill_the_page_buffer(0x42);
	zassert_ok(ftl_store(the_last_page()));

	zassert_true(the_nand_page_holds(reserved_pages() + 1, 0x42));
}

ZTEST(ftl, test_after_starting_again_a_page_that_was_stored_loads_as_zeros)
{
	/* The table is in the SSD's buffer and nowhere else, so it does not outlive a start. */
	fill_the_page_buffer(0x51);
	zassert_ok(ftl_store(A_PAGE));

	zassert_ok(ftl_start());

	zassert_ok(ftl_load(A_PAGE));
	zassert_true(the_page_buffer_is_all_zeros());
}

ZTEST_SUITE(ftl, NULL, NULL, start_with_an_empty_table, NULL, NULL);
