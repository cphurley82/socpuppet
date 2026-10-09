/*
 * NVMe, as much of it as this firmware speaks, from the NVMe base
 * specification, which is public.
 */

#ifndef FIRMWARE_SSD_NVME_H_
#define FIRMWARE_SSD_NVME_H_

#include <stdint.h>

#include <zephyr/sys/byteorder.h>

/* A drive's block is 512 bytes. */
#define NVME_BLOCK_SIZE    512
/*
 * The host says where a command's data is in pages of its memory, of 4 KiB
 * each.
 */
#define NVME_HOST_PAGE     4096
/* There is one namespace, and namespaces are numbered from 1. */
#define NVME_THE_NAMESPACE 1

/*
 * A command: 64 bytes, as the host wrote them into a submission queue.
 * Numbers in it are little-endian, wherever the firmware runs.
 */
struct nvme_command {
	uint8_t bytes[64];
};

static inline uint8_t nvme_opcode(const struct nvme_command *command)
{
	return command->bytes[0];
}

/* One of the command's sixteen 32-bit words, counted from 0. */
static inline uint32_t nvme_dword(const struct nvme_command *command, unsigned int number)
{
	return sys_get_le32(&command->bytes[4 * number]);
}

static inline uint32_t nvme_namespace(const struct nvme_command *command)
{
	return nvme_dword(command, 1);
}

/*
 * Where the command's data is in the host's memory: its first page, and
 * either its second page or a list of the rest (see data.h).
 */
static inline uint64_t nvme_data(const struct nvme_command *command)
{
	return sys_get_le64(&command->bytes[24]);
}

static inline uint64_t nvme_more_data(const struct nvme_command *command)
{
	return sys_get_le64(&command->bytes[32]);
}

/* Admin commands. */
#define NVME_CREATE_IO_SUBMISSION_QUEUE 0x01
#define NVME_CREATE_IO_COMPLETION_QUEUE 0x05
#define NVME_IDENTIFY                   0x06
#define NVME_SET_FEATURES               0x09

/* I/O commands. */
#define NVME_FLUSH 0x00
#define NVME_WRITE 0x01
#define NVME_READ  0x02

/*
 * How a command went. A status is a code and which list the code is from:
 * the one every command shares (type 0), or the command's own (type 1).
 * Here the code is the low byte and the type is above it, which is how the
 * NVMe frontend takes it.
 */
#define NVME_OF_THE_COMMAND(code) (0x100 | (code))

#define NVME_SUCCESS             0x00
#define NVME_INVALID_OPCODE      0x01
#define NVME_INVALID_FIELD       0x02
#define NVME_DATA_TRANSFER_ERROR 0x04
#define NVME_INTERNAL_ERROR      0x06
#define NVME_INVALID_NAMESPACE   0x0B
#define NVME_PRP_OFFSET_INVALID  0x13
#define NVME_LBA_OUT_OF_RANGE    0x80

/* Of the two commands that create a queue. */
#define NVME_COMPLETION_QUEUE_INVALID NVME_OF_THE_COMMAND(0x00)
#define NVME_INVALID_QUEUE_IDENTIFIER NVME_OF_THE_COMMAND(0x01)
#define NVME_INVALID_QUEUE_SIZE       NVME_OF_THE_COMMAND(0x02)
#define NVME_INVALID_INTERRUPT_VECTOR NVME_OF_THE_COMMAND(0x08)

/* What a command's completion will say: its status, and its answer. */
struct nvme_outcome {
	uint16_t status;
	/* For the few commands that have an answer of 32 bits. */
	uint32_t result;
};

#endif /* FIRMWARE_SSD_NVME_H_ */
