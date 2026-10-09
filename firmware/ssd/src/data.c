/* Where a command's data is in the host's memory. See data.h. */

#include "data.h"

#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>

#include <socpuppet/drivers/dma_engine.h>

#include "ssd.h"

/* A pointer in a list is 64 bits. */
#define POINTER_SIZE 8

void data_begin(struct data *data, const struct nvme_command *command, uint32_t length)
{
	*data = (struct data){
		.first = nvme_data(command),
		.second = nvme_more_data(command),
		.left = length,
		.from = DATA_AT_THE_FIRST_POINTER,
	};
}

/*
 * Fetches as much of the list at `list` as its page of the host's memory
 * holds, into the scratch page.
 */
static uint16_t fetch_the_list(struct data *data, uint64_t list)
{
	uint32_t bytes = NVME_HOST_PAGE - (uint32_t)(list % NVME_HOST_PAGE);

	/* A list starts where a pointer can. */
	if (list % POINTER_SIZE != 0) {
		return NVME_PRP_OFFSET_INVALID;
	}
	if (dma_engine_copy_from_host(ssd_dma, list, ssd_scratch(), bytes) != 0) {
		return NVME_DATA_TRANSFER_ERROR;
	}
	data->pointers = bytes / POINTER_SIZE;
	data->next = 0;

	return NVME_SUCCESS;
}

static uint64_t pointer(uint32_t number)
{
	return sys_get_le64(ssd_scratch() + (POINTER_SIZE * number));
}

uint16_t data_next(struct data *data, struct data_piece *piece)
{
	uint16_t status;

	*piece = (struct data_piece){0};
	if (data->left == 0) {
		return NVME_SUCCESS;
	}

	switch (data->from) {
	case DATA_AT_THE_FIRST_POINTER:
		/* From wherever in its page the data starts, to the page's end. */
		piece->address = data->first;
		piece->length =
			MIN(data->left, NVME_HOST_PAGE - (uint32_t)(data->first % NVME_HOST_PAGE));
		data->from = DATA_AT_THE_SECOND_POINTER;
		break;
	case DATA_AT_THE_SECOND_POINTER:
		if (data->left <= NVME_HOST_PAGE) {
			piece->address = data->second;
			piece->length = data->left;
			break;
		}
		/* More than a page is left, so the second pointer is to a list. */
		status = fetch_the_list(data, data->second);
		if (status != NVME_SUCCESS) {
			return status;
		}
		data->from = DATA_IN_A_LIST;
		__fallthrough;
	case DATA_IN_A_LIST:
		/*
		 * The last pointer of a list that fills its page points on to
		 * more of the list, if more than one page of data is to come.
		 */
		if (data->next == data->pointers - 1 && data->left > NVME_HOST_PAGE) {
			status = fetch_the_list(data, pointer(data->next));
			if (status != NVME_SUCCESS) {
				return status;
			}
		}
		piece->address = pointer(data->next++);
		piece->length = MIN(data->left, NVME_HOST_PAGE);
		break;
	}
	data->left -= piece->length;

	return NVME_SUCCESS;
}
