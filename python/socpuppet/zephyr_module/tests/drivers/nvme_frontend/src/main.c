/*
 * The driver of the SSD's NVMe frontend, with a host in front of it.
 *
 * A frontend only has something to say when a host speaks to it, so the
 * suite is built with the shield `socpuppet_ssd_host`, which is a host:
 * the stand-in `socpuppet run` puts in front of the SSD
 * (`_a_hosts_first_words` in socpuppet's run.py). It says what a host says
 * to a drive first. It enables the controller and waits for it to be
 * ready, and then sends five commands, each when the one before has
 * completed: three to get a pair of I/O queues, one to ask how big the
 * drive is, and then, on its new I/O queue, a write of one block.
 *
 * The suite is the firmware for that, once: it serves the host as the
 * header of the driver says a firmware does, and writes down what it was
 * told and what it read. Each case is about one thing it saw.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/toolchain.h>
#include <zephyr/ztest.h>

#include <socpuppet/drivers/dma_engine.h>
#include <socpuppet/drivers/nvme_frontend.h>

BUILD_ASSERT(IS_ENABLED(CONFIG_SHIELD_SOCPUPPET_SSD_HOST),
	     "Build this with -DSHIELD=socpuppet_ssd_host: with no host to speak to it, the "
	     "suite waits for ever.");

/* What the host sends, in the order it sends them, by their NVMe opcodes. */
#define SET_FEATURES            0x09
#define CREATE_COMPLETION_QUEUE 0x05
#define CREATE_SUBMISSION_QUEUE 0x01
#define IDENTIFY                0x06
#define WRITE                   0x01
enum {
	THE_SET_FEATURES,
	THE_FIRST_CREATE,
	THE_SECOND_CREATE,
	THE_IDENTIFY,
	THE_WRITE,
	COMMANDS_THE_HOST_SENDS,
};
/* Set Features says which feature in its tenth word: 7 is how many queues. */
#define NUMBER_OF_QUEUES 0x07
/* The queue the host has from the start, and the first it asks for. */
#define ADMIN_QUEUE      0
#define FIRST_IO_QUEUE   1

/* Where things are in a command: its bytes are little-endian words. */
#define OPCODE_AT     0
#define IDENTIFIER_AT 2
#define DATA_AT       24
#define WORD_10_AT    40
#define WORD_11_AT    44

/*
 * What a drive says of itself when asked: a page, of which the host reads
 * three things. How many blocks, at the start, which of its formats is in
 * use, and what that format is: its block size as a power of two.
 */
#define DESCRIPTION_SIZE 4096
#define BLOCKS_AT        0
#define FORMAT_IN_USE_AT 26
#define FIRST_FORMAT_AT  128
#define BLOCKS_OF_512    (9 << 16)

static const struct device *const frontend = DEVICE_DT_GET_ONE(socpuppet_nvme_frontend);
static const struct device *const dma = DEVICE_DT_GET_ONE(socpuppet_dma_engine);
/* The engine copies from the SSD's buffer, and not from the CPU's own memory. */
static uint8_t *const description = (uint8_t *)DT_REG_ADDR(DT_NODELABEL(ssd_buffer));

static struct {
	/* How many times nvme_frontend_wait() said the host had enabled the controller. */
	unsigned int times_told_of_the_enabling;
	uint8_t commands[COMMANDS_THE_HOST_SENDS][NVME_FRONTEND_COMMAND_SIZE];
	uint16_t came_from[COMMANDS_THE_HOST_SENDS];
	struct nvme_frontend_limits limits;
} saw;

/* Has the frontend take the queue a Create command asks for. */
static void create_the_queue(const uint8_t *command, uint32_t kind)
{
	uint32_t size_and_id = sys_get_le32(&command[WORD_10_AT]);
	struct nvme_frontend_queue queue = {
		.kind = kind,
		.id = (uint16_t)size_and_id,
		.base = sys_get_le64(&command[DATA_AT]),
		.last_slot = (uint16_t)(size_and_id >> 16),
		/* The vector, or the completion queue: the word's high half. */
		.link = (uint16_t)(sys_get_le32(&command[WORD_11_AT]) >> 16),
	};

	nvme_frontend_create_queue(frontend, &queue);
}

/* Sends the host the page it asked for: a drive of one block of 512 bytes. */
static void describe_the_drive(const uint8_t *command)
{
	memset(description, 0, DESCRIPTION_SIZE);
	sys_put_le64(1, &description[BLOCKS_AT]);
	description[FORMAT_IN_USE_AT] = 0;
	sys_put_le32(BLOCKS_OF_512, &description[FIRST_FORMAT_AT]);

	zassert_ok(dma_engine_copy_to_host(dma, sys_get_le64(&command[DATA_AT]), description,
					   DESCRIPTION_SIZE));
}

/* Does what the admin command asks, as far as this host looks. */
static void do_the_admin_command(const uint8_t *command)
{
	switch (command[OPCODE_AT]) {
	case CREATE_COMPLETION_QUEUE:
		create_the_queue(command, NVME_FRONTEND_QUEUE_CREATE_COMPLETION_QUEUE);
		break;
	case CREATE_SUBMISSION_QUEUE:
		create_the_queue(command, NVME_FRONTEND_QUEUE_CREATE_SUBMISSION_QUEUE);
		break;
	case IDENTIFY:
		describe_the_drive(command);
		break;
	default:
		break;
	}
}

static void *serve_a_host_that_says_its_first_words(void)
{
	size_t served = 0;

	zassert_true(device_is_ready(frontend));
	zassert_true(device_is_ready(dma));
	nvme_frontend_get_limits(frontend, &saw.limits);

	while (served < COMMANDS_THE_HOST_SENDS) {
		uint32_t happened = nvme_frontend_wait(frontend);

		if (happened & NVME_FRONTEND_STATUS_DISABLED) {
			nvme_frontend_acknowledge(frontend, NVME_FRONTEND_STATUS_DISABLED);
		}
		if (happened & NVME_FRONTEND_STATUS_ENABLED) {
			++saw.times_told_of_the_enabling;
			nvme_frontend_acknowledge(frontend, NVME_FRONTEND_STATUS_ENABLED);
			nvme_frontend_say_ready(frontend);
		}
		if (happened & NVME_FRONTEND_STATUS_COMMAND_WAITING) {
			uint8_t *command = saw.commands[served];

			saw.came_from[served] = nvme_frontend_read_command(frontend, command);
			if (saw.came_from[served] == ADMIN_QUEUE) {
				do_the_admin_command(command);
			}
			/* Success, and no answer: none of the five has one. */
			nvme_frontend_post(frontend, 0, 0);
			++served;
		}
	}

	return NULL;
}

ZTEST(nvme_frontend, test_an_enabling_that_was_acknowledged_is_not_reported_again)
{
	zassert_equal(saw.times_told_of_the_enabling, 1, "it was reported %u times",
		      saw.times_told_of_the_enabling);
}

ZTEST(nvme_frontend, test_the_hosts_first_command_is_read_as_the_host_wrote_it)
{
	const uint8_t *first = saw.commands[THE_SET_FEATURES];

	zassert_equal(first[OPCODE_AT], SET_FEATURES, "the opcode was 0x%02x", first[OPCODE_AT]);
	/* A word from further along, where a read that stopped short has none. */
	zassert_equal(sys_get_le32(&first[WORD_10_AT]), NUMBER_OF_QUEUES);
}

ZTEST(nvme_frontend, test_once_a_completion_is_posted_the_next_command_read_is_a_new_one)
{
	/* The host numbers its commands on a queue, in the bytes after the opcode. */
	zassert_not_equal(sys_get_le16(&saw.commands[THE_SET_FEATURES][IDENTIFIER_AT]),
			  sys_get_le16(&saw.commands[THE_FIRST_CREATE][IDENTIFIER_AT]));
	zassert_not_equal(sys_get_le16(&saw.commands[THE_FIRST_CREATE][IDENTIFIER_AT]),
			  sys_get_le16(&saw.commands[THE_SECOND_CREATE][IDENTIFIER_AT]));
}

ZTEST(nvme_frontend, test_a_command_on_a_queue_the_frontend_was_told_to_create_is_fetched)
{
	/*
	 * The frontend takes a doorbell only for a queue it has, so the
	 * write arriving at all is the queue having been created.
	 */
	zassert_equal(saw.commands[THE_WRITE][OPCODE_AT], WRITE);
}

ZTEST(nvme_frontend, test_a_command_says_which_queue_it_came_from)
{
	zassert_equal(saw.came_from[THE_IDENTIFY], ADMIN_QUEUE);
	zassert_equal(saw.came_from[THE_WRITE], FIRST_IO_QUEUE);
}

ZTEST(nvme_frontend, test_the_limits_are_the_boards)
{
	/* socpuppet's SSD has two vectors for its host, and eight pairs of I/O queues. */
	zassert_equal(saw.limits.vectors, 2, "%u vectors", saw.limits.vectors);
	zassert_equal(saw.limits.io_queue_pairs, 8, "%u pairs", saw.limits.io_queue_pairs);
}

ZTEST_SUITE(nvme_frontend, NULL, serve_a_host_that_says_its_first_words, NULL, NULL, NULL);
