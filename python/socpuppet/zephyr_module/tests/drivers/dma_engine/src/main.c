/*
 * The driver of the SSD's DMA engine: copies between the host's memory and
 * the SSD's own, both ways, and what it says of a copy that cannot be
 * made.
 *
 * The host is a stand-in, the one `socpuppet run` puts in front of the SSD
 * for the shield `socpuppet_ssd_host` (socpuppet's
 * boards/scripted_host.py). Its memory is where a real host's is: a
 * megabyte from 0x8000_0000. The engine copies to and from the SSD's
 * buffer, which is the memory it reaches, and not the CPU's own.
 *
 * A PCIe device may not reach into its host's memory until the host has
 * switched that on for it (the bus master bit of the device's command
 * register), which a host does when it finds the device. Until then every
 * copy is refused. So the suite first waits for a copy to be made.
 */

#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/kernel.h>
#include <zephyr/toolchain.h>
#include <zephyr/ztest.h>

#include <socpuppet/drivers/dma_engine.h>

BUILD_ASSERT(IS_ENABLED(CONFIG_SHIELD_SOCPUPPET_SSD_HOST),
	     "Build this with -DSHIELD=socpuppet_ssd_host: with no host to allow it, no copy "
	     "is made.");

/* Half way into the host's megabyte, and so clear of both its ends. */
#define IN_THE_HOSTS_MEMORY    0x80080000ULL
/* The same place with a bit above the 32nd set, where the host has nothing. */
#define ABOVE_THE_HOSTS_MEMORY (IN_THE_HOSTS_MEMORY | BIT64(32))
/* Past the end of the host's megabyte, where it has nothing either. */
#define PAST_THE_HOSTS_MEMORY  0x90000000ULL

#define BUFFER      DT_NODELABEL(ssd_buffer)
#define BUFFER_BASE ((uint8_t *)DT_REG_ADDR(BUFFER))
#define BUFFER_SIZE DT_REG_SIZE(BUFFER)

/* Three of the host's pages and a bit: more than one of anything. */
#define SEVERAL_PAGES (3 * 4096 + 5)

static const struct device *const dma = DEVICE_DT_GET_ONE(socpuppet_dma_engine);
/* Two places in the SSD's buffer that do not overlap. */
static uint8_t *const sent = BUFFER_BASE;
static uint8_t *const fetched = BUFFER_BASE + 2 * SEVERAL_PAGES;

/*
 * The host finds the drive in its first few microseconds, and Zephyr takes
 * longer than that to start. This is patience for a host that is slower.
 */
#define PATIENCE_MS 100

static void *wait_until_the_host_allows_dma(void)
{
	zassert_true(device_is_ready(dma));
	for (int waited = 0; waited < PATIENCE_MS; ++waited) {
		if (dma_engine_copy_to_host(dma, IN_THE_HOSTS_MEMORY, sent, 1) == 0) {
			return NULL;
		}
		k_msleep(1);
	}
	zassert_unreachable("the host never let the drive reach its memory");

	return NULL;
}

/* What is sent: no two neighbours the same, and no two pages alike. */
static uint8_t pattern_at(size_t at)
{
	return (uint8_t)(at * 7 + at / 4096);
}

static void before_each(void *fixture)
{
	ARG_UNUSED(fixture);

	for (size_t at = 0; at < SEVERAL_PAGES; ++at) {
		sent[at] = pattern_at(at);
	}
	memset(fetched, 0, SEVERAL_PAGES);
}

/* Whether `length` bytes at `bytes` are the pattern from its beginning. */
static bool is_the_pattern(const uint8_t *bytes, size_t length)
{
	for (size_t at = 0; at < length; ++at) {
		if (bytes[at] != pattern_at(at)) {
			return false;
		}
	}

	return true;
}

ZTEST(dma_engine, test_what_is_copied_to_the_host_is_what_is_copied_back_from_it)
{
	zassert_ok(dma_engine_copy_to_host(dma, IN_THE_HOSTS_MEMORY, sent, 64));
	zassert_ok(dma_engine_copy_from_host(dma, IN_THE_HOSTS_MEMORY, fetched, 64));

	/* Held to the pattern, and not to `sent`, which a copy the wrong way would change. */
	zassert_true(is_the_pattern(fetched, 64));
}

ZTEST(dma_engine, test_a_copy_of_several_pages_and_a_bit_arrives_whole)
{
	zassert_ok(dma_engine_copy_to_host(dma, IN_THE_HOSTS_MEMORY, sent, SEVERAL_PAGES));
	zassert_ok(dma_engine_copy_from_host(dma, IN_THE_HOSTS_MEMORY, fetched, SEVERAL_PAGES));

	zassert_true(is_the_pattern(fetched, SEVERAL_PAGES));
}

ZTEST(dma_engine, test_a_copy_from_the_host_leaves_what_is_beside_it_alone)
{
	zassert_ok(dma_engine_copy_to_host(dma, IN_THE_HOSTS_MEMORY, sent, 64));
	memset(fetched, 0xA5, 64 + 2);

	zassert_ok(dma_engine_copy_from_host(dma, IN_THE_HOSTS_MEMORY, fetched + 1, 64));

	zassert_true(is_the_pattern(fetched + 1, 64));
	zassert_equal(fetched[0], 0xA5);
	zassert_equal(fetched[64 + 1], 0xA5);
}

ZTEST(dma_engine, test_a_host_address_above_four_gigabytes_is_not_cut_to_32_bits)
{
	/*
	 * Cut short, this would be the host's memory, and the copy would be
	 * made. Whole, it is an address where the host has nothing.
	 */
	zassert_equal(dma_engine_copy_to_host(dma, ABOVE_THE_HOSTS_MEMORY, sent, 64), -EIO);
}

ZTEST(dma_engine, test_a_copy_from_where_the_host_has_nothing_is_an_error)
{
	zassert_equal(dma_engine_copy_from_host(dma, PAST_THE_HOSTS_MEMORY, fetched, 64), -EIO);
}

ZTEST(dma_engine, test_a_copy_to_where_the_ssd_has_nothing_is_an_error)
{
	uint8_t *past_the_buffer = BUFFER_BASE + BUFFER_SIZE;

	zassert_equal(dma_engine_copy_from_host(dma, IN_THE_HOSTS_MEMORY, past_the_buffer, 64),
		      -EIO);
}

ZTEST_SUITE(dma_engine, NULL, wait_until_the_host_allows_dma, before_each, NULL, NULL);
