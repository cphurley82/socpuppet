/*
 * The admin commands: Identify, Set Features, and the two that create an
 * I/O queue.
 */

#include <stdbool.h>
#include <string.h>

#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>

#include <socpuppet/drivers/dma_engine.h>
#include <socpuppet/drivers/nvme_frontend.h>

#include "data.h"
#include "ssd.h"

/* What Identify can be asked for. */
#define THE_NAMESPACE_ITSELF  0x00
#define THE_CONTROLLER        0x01
#define THE_ACTIVE_NAMESPACES 0x02

/* The one feature there is to set. */
#define NUMBER_OF_QUEUES 0x07

/*
 * The I/O queues the host has had created, by identifier. The frontend
 * keeps the queues themselves. This is the firmware's own record of which
 * exist, which it needs to tell the host what it may not have.
 */
#define MOST_QUEUE_PAIRS 64
static bool completion_queues[MOST_QUEUE_PAIRS + 1];
static bool submission_queues[MOST_QUEUE_PAIRS + 1];

void admin_forget_the_queues(void)
{
	memset(completion_queues, 0, sizeof(completion_queues));
	memset(submission_queues, 0, sizeof(submission_queues));
}

/* What the frontend has, and so what the host may ask for. */
static struct nvme_frontend_limits limits;

void admin_start(void)
{
	nvme_frontend_get_limits(ssd_frontend, &limits);
	limits.io_queue_pairs = MIN(limits.io_queue_pairs, MOST_QUEUE_PAIRS);
}

/* Sends the scratch page to where a command's data goes. */
static uint16_t send_the_scratch_page(const struct nvme_command *command)
{
	/* What is left of the page to send. */
	const uint8_t *from = ssd_scratch();
	struct data data;
	struct data_piece piece;
	uint16_t status;

	/*
	 * One page of data is in one piece, or two if it does not start at the
	 * start of a page of the host's memory. It never needs a list, which
	 * is as well: a list would be fetched into the scratch page.
	 */
	data_begin(&data, command, NVME_HOST_PAGE);
	while ((status = data_next(&data, &piece)) == NVME_SUCCESS && piece.length != 0) {
		if (dma_engine_copy_to_host(ssd_dma, piece.address, from, piece.length) != 0) {
			return NVME_DATA_TRANSFER_ERROR;
		}
		from += piece.length;
	}

	return status;
}

/*
 * Identify: the host asks what the controller is and what it holds, and
 * gets a 4 KiB page of description back.
 */
static uint16_t identify(const struct nvme_command *command)
{
	uint8_t *page = ssd_scratch();
	uint64_t blocks = io_drive_blocks();

	memset(page, 0, NVME_HOST_PAGE);
	switch (nvme_dword(command, 10) & 0xFF) {
	case THE_CONTROLLER:
		/* How many namespaces there are, at offset 516. */
		sys_put_le32(1, &page[516]);
		break;
	case THE_NAMESPACE_ITSELF:
		if (nvme_namespace(command) != NVME_THE_NAMESPACE) {
			return NVME_INVALID_NAMESPACE;
		}
		/*
		 * Its size and its capacity in blocks, and at offset 128 the
		 * first block format, whose third byte is the block size as a
		 * power of two: 2 to the 9th is 512.
		 */
		sys_put_le64(blocks, &page[0]);
		sys_put_le64(blocks, &page[8]);
		page[130] = 9;
		break;
	case THE_ACTIVE_NAMESPACES:
		sys_put_le32(NVME_THE_NAMESPACE, &page[0]);
		break;
	default:
		return NVME_INVALID_FIELD;
	}

	return send_the_scratch_page(command);
}

/*
 * Set Features: the host changes a setting. The one every driver changes
 * is how many I/O queues it would like.
 */
static struct nvme_outcome set_features(const struct nvme_command *command)
{
	/*
	 * The answer is how many I/O queues the drive has, whatever the host
	 * asked for, counted from zero: submission queues in the low half,
	 * completion queues in the high half.
	 */
	uint32_t from_zero = limits.io_queue_pairs - 1;

	if ((nvme_dword(command, 10) & 0xFF) != NUMBER_OF_QUEUES) {
		return (struct nvme_outcome){.status = NVME_INVALID_FIELD};
	}

	return (struct nvme_outcome){.status = NVME_SUCCESS, .result = from_zero << 16 | from_zero};
}

/*
 * Whether the host may have an I/O queue with this identifier. Queue 0 is
 * the admin queue, and there are only so many.
 */
static bool is_an_io_queue(uint32_t queue_id)
{
	return queue_id >= 1 && queue_id <= limits.io_queue_pairs;
}

/*
 * Create I/O Completion Queue, and Create I/O Submission Queue. The host
 * has set a ring aside in its memory and says where it is and how long.
 * Both are asked for the same way: the identifier in the low half of dword
 * 10, the size, counted from zero, in the high half, and where the queue
 * is in the first data pointer.
 *
 * The firmware decides whether the host may have the queue, and if so has
 * the frontend create it.
 */
static uint16_t create_queue(const struct nvme_command *command, enum nvme_frontend_queue_kind kind)
{
	bool *queues =
		kind == NVME_FRONTEND_COMPLETION_QUEUE ? completion_queues : submission_queues;
	struct nvme_frontend_queue queue = {
		.kind = kind,
		.id = nvme_dword(command, 10) & 0xFFFF,
		.base = nvme_data(command),
		.last_slot = nvme_dword(command, 10) >> 16,
		/*
		 * A completion queue's interrupt vector, or the completion
		 * queue of a submission queue: either way, the high half of
		 * dword 11.
		 */
		.link = nvme_dword(command, 11) >> 16,
	};

	if (!is_an_io_queue(queue.id) || queues[queue.id]) {
		return NVME_INVALID_QUEUE_IDENTIFIER;
	}
	/* A queue keeps one slot empty, so one of a single entry holds nothing. */
	if (queue.last_slot == 0) {
		return NVME_INVALID_QUEUE_SIZE;
	}
	if (kind == NVME_FRONTEND_COMPLETION_QUEUE) {
		/* The vector has to be one the drive has. */
		if (queue.link >= limits.vectors) {
			return NVME_INVALID_INTERRUPT_VECTOR;
		}
	} else if (queue.link != 0 &&
		   (!is_an_io_queue(queue.link) || !completion_queues[queue.link])) {
		/*
		 * The completion queue has to be there first. The admin
		 * completion queue, number 0, always is.
		 */
		return NVME_COMPLETION_QUEUE_INVALID;
	}

	nvme_frontend_create_queue(ssd_frontend, &queue);
	queues[queue.id] = true;

	return NVME_SUCCESS;
}

struct nvme_outcome admin_command(const struct nvme_command *command)
{
	switch (nvme_opcode(command)) {
	case NVME_CREATE_IO_COMPLETION_QUEUE:
		return (struct nvme_outcome){
			.status = create_queue(command, NVME_FRONTEND_COMPLETION_QUEUE)};
	case NVME_CREATE_IO_SUBMISSION_QUEUE:
		return (struct nvme_outcome){
			.status = create_queue(command, NVME_FRONTEND_SUBMISSION_QUEUE)};
	case NVME_IDENTIFY:
		return (struct nvme_outcome){.status = identify(command)};
	case NVME_SET_FEATURES:
		return set_features(command);
	default:
		return (struct nvme_outcome){.status = NVME_INVALID_OPCODE};
	}
}
