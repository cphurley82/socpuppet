/* The I/O commands: Read, Write and Flush, on the one namespace. */

#include <stdbool.h>

#include <zephyr/sys/util.h>

#include <socpuppet/drivers/dma_engine.h>

#include "data.h"
#include "ftl.h"
#include "ssd.h"

uint64_t io_drive_blocks(void)
{
	return (uint64_t)ftl_pages() * (ftl_page_size() / NVME_BLOCK_SIZE);
}

/*
 * Read: the host asks for blocks, and they are copied into its memory.
 * Write: the other way.
 *
 * The command's data is in pieces, one for each page of the host's memory,
 * and the drive is in pages too, which do not line up with the host's. So
 * the firmware works through the drive a page at a time: it puts the page
 * in the buffer once, moves every piece of the data that is in that page,
 * and for a write programs the page once.
 */
static uint16_t read_or_write(const struct nvme_command *command)
{
	bool writing = nvme_opcode(command) == NVME_WRITE;
	/*
	 * NVMe calls a block's number its LBA, logical block address. The
	 * first is in dwords 10 and 11, and how many blocks, counted from
	 * zero, in the low half of dword 12.
	 */
	uint64_t first = (uint64_t)nvme_dword(command, 11) << 32 | nvme_dword(command, 10);
	uint32_t count = (nvme_dword(command, 12) & 0xFFFF) + 1;
	uint64_t at = first * NVME_BLOCK_SIZE;
	/* Which page of the drive is in the buffer, if one is. */
	bool have_a_page = false;
	uint32_t in_the_buffer = 0;
	struct data data;
	struct data_piece piece;
	uint16_t status;

	if (nvme_namespace(command) != NVME_THE_NAMESPACE) {
		return NVME_INVALID_NAMESPACE;
	}
	if (first > io_drive_blocks() || count > io_drive_blocks() - first) {
		return NVME_LBA_OUT_OF_RANGE;
	}

	data_begin(&data, command, count * NVME_BLOCK_SIZE);
	for (;;) {
		status = data_next(&data, &piece);
		if (status != NVME_SUCCESS) {
			return status;
		}
		if (piece.length == 0) {
			break;
		}
		/* A piece ends where the drive's page does, if that is sooner. */
		while (piece.length != 0) {
			uint32_t page = at / ftl_page_size();
			uint32_t offset = at % ftl_page_size();
			uint32_t length = MIN(piece.length, ftl_page_size() - offset);
			uint8_t *in_the_page = ssd_page_buffer() + offset;
			int result;

			if (!have_a_page || page != in_the_buffer) {
				if (writing && have_a_page && ftl_store(in_the_buffer) != 0) {
					return NVME_INTERNAL_ERROR;
				}
				if (ftl_load(page) != 0) {
					return NVME_INTERNAL_ERROR;
				}
				in_the_buffer = page;
				have_a_page = true;
			}
			result = writing ? dma_engine_copy_from_host(ssd_dma, piece.address,
								     in_the_page, length)
					 : dma_engine_copy_to_host(ssd_dma, piece.address,
								   in_the_page, length);
			if (result != 0) {
				return NVME_DATA_TRANSFER_ERROR;
			}
			at += length;
			piece.address += length;
			piece.length -= length;
		}
	}
	if (writing && have_a_page && ftl_store(in_the_buffer) != 0) {
		return NVME_INTERNAL_ERROR;
	}

	return NVME_SUCCESS;
}

struct nvme_outcome io_command(const struct nvme_command *command)
{
	switch (nvme_opcode(command)) {
	case NVME_FLUSH:
		/* Everything written is already in the NAND. */
		return (struct nvme_outcome){.status = NVME_SUCCESS};
	case NVME_READ:
	case NVME_WRITE:
		return (struct nvme_outcome){.status = read_or_write(command)};
	default:
		return (struct nvme_outcome){.status = NVME_INVALID_OPCODE};
	}
}
