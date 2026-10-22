/*
 * The admin commands of the SSD's firmware (../../src/admin.c), a command
 * at a time: what the firmware answers, and what it refuses and why.
 *
 * The test is the firmware here, and its own host too. It makes up each
 * command as a host would write it and hands it to admin_command(), which
 * is what the firmware's main loop does with a command from the admin
 * queue. Where a command's answer is a page in the host's memory, the test
 * fetches the page back with the DMA engine to read it.
 *
 * That page is why the suite is built with the shield
 * `socpuppet_ssd_host`: a PCIe device may not reach into its host's memory
 * until a host has switched that on, and the shield's host does. Nothing
 * else it does is used here, and it is never told the drive is ready. It
 * waits a second of simulated time for that before it gives up and ends
 * the run, so the suite has to be done by then, and is in a tenth of it.
 */

#include <stdint.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/toolchain.h>
#include <zephyr/ztest.h>

#include <socpuppet/drivers/dma_engine.h>
#include <socpuppet/drivers/nvme_frontend.h>

#include "ftl.h"
#include "ssd.h"

BUILD_ASSERT(IS_ENABLED(CONFIG_SHIELD_SOCPUPPET_SSD_HOST),
	     "Build this with -DSHIELD=socpuppet_ssd_host: with no host to allow it, Identify's "
	     "page cannot be copied to one.");

/* The firmware's main.c says which devices are which. Here this does. */
const struct device *const ssd_frontend = DEVICE_DT_GET_ONE(socpuppet_nvme_frontend);
const struct device *const ssd_dma = DEVICE_DT_GET_ONE(socpuppet_dma_engine);
const struct device *const ssd_nand = DEVICE_DT_GET_ONE(socpuppet_flash_controller);

/* Half way into the host's megabyte, on a page boundary, for a command's data. */
#define IN_THE_HOSTS_MEMORY   0x80080000ULL
/* Past the end of the host's megabyte, where it has nothing. */
#define PAST_THE_HOSTS_MEMORY 0x90000000ULL

/* What Identify is asked for, in the low byte of its tenth word. */
#define THE_NAMESPACE_ITSELF  0x00
#define THE_CONTROLLER        0x01
#define THE_ACTIVE_NAMESPACES 0x02
#define SOMETHING_ELSE        0x7F
/* Set Features' one feature, and one it does not have. */
#define NUMBER_OF_QUEUES      0x07
#define ANOTHER_FEATURE       0x01
/* An opcode that is no admin command of this drive's. */
#define NO_COMMAND            0x7F

/* Where things are in a command. */
#define NAMESPACE_AT 4
#define DATA_AT      24
#define WORD_10_AT   40
#define WORD_11_AT   44

/*
 * The host finds the drive in its first few microseconds, and Zephyr takes
 * longer than that to start. This is patience for a host that is slower.
 */
#define PATIENCE_MS 100

/* How long a queue is, counted from zero as a Create command says it. */
#define SIXTEEN_ENTRIES 15
#define ONE_ENTRY       0
/* How many bytes one of the host's blocks is. */
#define BLOCK_SIZE      512

static struct nvme_frontend_limits limits;
/*
 * The page the host was sent, fetched back into the firmware's scratch
 * page, which is what the scratch page is for.
 */
static uint8_t *fetched;

static struct nvme_command a_command(uint8_t opcode, uint32_t word_10, uint32_t word_11)
{
	struct nvme_command command = {0};

	command.bytes[0] = opcode;
	sys_put_le32(NVME_THE_NAMESPACE, &command.bytes[NAMESPACE_AT]);
	sys_put_le64(IN_THE_HOSTS_MEMORY, &command.bytes[DATA_AT]);
	sys_put_le32(word_10, &command.bytes[WORD_10_AT]);
	sys_put_le32(word_11, &command.bytes[WORD_11_AT]);

	return command;
}

/* Create a queue: its identifier and its size from zero, and what goes with it. */
static struct nvme_command a_create(uint8_t opcode, uint16_t id, uint16_t last_slot,
				    uint16_t goes_with)
{
	return a_command(opcode, (uint32_t)last_slot << 16 | id, (uint32_t)goes_with << 16);
}

/* Identify, answered, and the page the host got fetched back. */
static void identify(uint8_t what)
{
	struct nvme_command command = a_command(NVME_IDENTIFY, what, 0);

	zassert_equal(admin_command(&command).status, NVME_SUCCESS);
	/* So that what is read next came from the host, and is not what was sent. */
	memset(fetched, 0xA5, NVME_HOST_PAGE);
	zassert_ok(
		dma_engine_copy_from_host(ssd_dma, IN_THE_HOSTS_MEMORY, fetched, NVME_HOST_PAGE));
}

static void *start_the_firmwares_parts(void)
{
	zassert_ok(ftl_start());
	admin_start();
	nvme_frontend_get_limits(ssd_frontend, &limits);
	fetched = ssd_scratch();

	for (int waited = 0; waited < PATIENCE_MS; ++waited) {
		if (dma_engine_copy_to_host(ssd_dma, IN_THE_HOSTS_MEMORY, fetched, 1) == 0) {
			return NULL;
		}
		k_msleep(1);
	}
	zassert_unreachable("the host never let the drive reach its memory");

	return NULL;
}

ZTEST(admin, test_an_opcode_that_is_no_admin_command_is_refused_as_that)
{
	struct nvme_command command = a_command(NO_COMMAND, 0, 0);

	zassert_equal(admin_command(&command).status, NVME_INVALID_OPCODE);
}

ZTEST(admin, test_identify_says_the_namespace_has_the_drives_blocks_of_512_bytes)
{
	/* The drive is the NAND less the FTL's reserve, in pages. */
	uint64_t drive_bytes = (uint64_t)ftl_pages() * ftl_page_size();

	identify(THE_NAMESPACE_ITSELF);

	/*
	 * Its size and its capacity, which are the drive's, and then the
	 * first format's block size, as a power of two.
	 */
	zassert_equal(sys_get_le64(&fetched[0]), drive_bytes / BLOCK_SIZE);
	zassert_equal(sys_get_le64(&fetched[8]), drive_bytes / BLOCK_SIZE);
	zassert_equal(1U << fetched[130], BLOCK_SIZE);
}

ZTEST(admin, test_identify_says_the_controller_has_one_namespace)
{
	identify(THE_CONTROLLER);

	zassert_equal(sys_get_le32(&fetched[516]), 1);
}

ZTEST(admin, test_identify_lists_the_one_namespace_as_active)
{
	identify(THE_ACTIVE_NAMESPACES);

	zassert_equal(sys_get_le32(&fetched[0]), NVME_THE_NAMESPACE);
	zassert_equal(sys_get_le32(&fetched[4]), 0);
}

ZTEST(admin, test_identify_of_a_namespace_there_is_not_is_refused)
{
	struct nvme_command command = a_command(NVME_IDENTIFY, THE_NAMESPACE_ITSELF, 0);

	sys_put_le32(NVME_THE_NAMESPACE + 1, &command.bytes[NAMESPACE_AT]);

	zassert_equal(admin_command(&command).status, NVME_INVALID_NAMESPACE);
}

ZTEST(admin, test_identify_of_something_it_cannot_describe_is_an_invalid_field)
{
	struct nvme_command command = a_command(NVME_IDENTIFY, SOMETHING_ELSE, 0);

	zassert_equal(admin_command(&command).status, NVME_INVALID_FIELD);
}

ZTEST(admin, test_identify_to_where_the_host_has_no_memory_is_a_data_transfer_error)
{
	struct nvme_command command = a_command(NVME_IDENTIFY, THE_CONTROLLER, 0);

	sys_put_le64(PAST_THE_HOSTS_MEMORY, &command.bytes[DATA_AT]);

	zassert_equal(admin_command(&command).status, NVME_DATA_TRANSFER_ERROR);
}

ZTEST(admin, test_set_features_answers_with_the_queues_the_drive_has_counted_from_zero)
{
	/* Whatever the host asked for: here, 200 of each. */
	struct nvme_command command =
		a_command(NVME_SET_FEATURES, NUMBER_OF_QUEUES, 199 << 16 | 199);
	uint32_t from_zero = limits.io_queue_pairs - 1;

	struct nvme_outcome outcome = admin_command(&command);

	zassert_equal(outcome.status, NVME_SUCCESS);
	zassert_equal(outcome.result, from_zero << 16 | from_zero, "the answer was 0x%08x",
		      outcome.result);
}

ZTEST(admin, test_set_features_for_a_feature_it_does_not_have_is_an_invalid_field)
{
	struct nvme_command command = a_command(NVME_SET_FEATURES, ANOTHER_FEATURE, 0);

	zassert_equal(admin_command(&command).status, NVME_INVALID_FIELD);
}

ZTEST(admin, test_a_queue_numbered_zero_is_refused_since_that_is_the_admin_queue)
{
	struct nvme_command command =
		a_create(NVME_CREATE_IO_COMPLETION_QUEUE, 0, SIXTEEN_ENTRIES, 0);

	zassert_equal(admin_command(&command).status, NVME_INVALID_QUEUE_IDENTIFIER);
}

ZTEST(admin, test_a_queue_numbered_past_what_the_drive_has_is_refused)
{
	struct nvme_command command = a_create(NVME_CREATE_IO_COMPLETION_QUEUE,
					       limits.io_queue_pairs + 1, SIXTEEN_ENTRIES, 0);

	zassert_equal(admin_command(&command).status, NVME_INVALID_QUEUE_IDENTIFIER);
}

ZTEST(admin, test_a_queue_of_one_entry_is_refused_since_it_could_hold_nothing)
{
	struct nvme_command command = a_create(NVME_CREATE_IO_COMPLETION_QUEUE, 1, ONE_ENTRY, 0);

	zassert_equal(admin_command(&command).status, NVME_INVALID_QUEUE_SIZE);
}

ZTEST(admin, test_a_completion_queue_on_a_vector_the_drive_has_not_got_is_refused)
{
	struct nvme_command command =
		a_create(NVME_CREATE_IO_COMPLETION_QUEUE, 1, SIXTEEN_ENTRIES, limits.vectors);

	zassert_equal(admin_command(&command).status, NVME_INVALID_INTERRUPT_VECTOR);
}

ZTEST(admin, test_a_submission_queue_whose_completion_queue_is_not_there_is_refused_as_that)
{
	struct nvme_command command =
		a_create(NVME_CREATE_IO_SUBMISSION_QUEUE, 1, SIXTEEN_ENTRIES, 1);

	zassert_equal(admin_command(&command).status, NVME_COMPLETION_QUEUE_INVALID);
}

ZTEST_SUITE(admin, NULL, start_the_firmwares_parts, NULL, NULL, NULL);
