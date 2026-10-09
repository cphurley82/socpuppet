/*
 * Where a command's data is in the host's memory, and moving it.
 *
 * NVMe says where data is page by page (PRPs, physical region pages). The
 * first pointer is to the data itself, and may start anywhere in a page of
 * the host's memory. If what is left after that page fits in one more, the
 * second pointer is to it. Otherwise the second pointer is to a list of
 * pointers, a page each, and a list that fills its own page ends with a
 * pointer to more of the list.
 *
 * So the data is in pieces, each inside one page of the host's memory, and
 * the firmware has to follow the pointers to find them:
 *
 *	struct data data;
 *	struct data_piece piece;
 *
 *	data_begin(&data, command, length);
 *	while ((status = data_next(&data, &piece)) == NVME_SUCCESS &&
 *	       piece.length != 0) {
 *		... move piece.length bytes at piece.address ...
 *	}
 */

#ifndef FIRMWARE_SSD_DATA_H_
#define FIRMWARE_SSD_DATA_H_

#include <stdint.h>

#include "nvme.h"

/* One piece of a command's data: a run of bytes in the host's memory. */
struct data_piece {
	uint64_t address;
	uint32_t length;
};

/* How far the firmware has got through a command's data. */
struct data {
	/* The command's two pointers. */
	uint64_t first;
	uint64_t second;
	/* How many bytes are still to come. */
	uint32_t left;
	/* Which pointer the next piece comes from. */
	enum {
		DATA_AT_THE_FIRST_POINTER,
		DATA_AT_THE_SECOND_POINTER,
		DATA_IN_A_LIST,
	} from;
	/*
	 * The list being followed: how many pointers of it are in the scratch
	 * page, and which is next.
	 */
	uint32_t pointers;
	uint32_t next;
};

/* Starts at the beginning of the `length` bytes of a command's data. */
void data_begin(struct data *data, const struct nvme_command *command, uint32_t length);

/*
 * Finds the next piece. Returns NVME_SUCCESS with the piece, whose length
 * is 0 when there is no more. Or returns how the command has failed: the
 * host's list of pointers is not where a list can be, or could not be
 * fetched.
 *
 * A list is fetched into the scratch page, so the scratch page is not for
 * anything else until the data has been gone through.
 */
uint16_t data_next(struct data *data, struct data_piece *piece);

#endif /* FIRMWARE_SSD_DATA_H_ */
