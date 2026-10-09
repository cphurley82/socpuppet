/* The SSD's buffer, and what is where in it. See ssd.h. */

#include <zephyr/devicetree.h>

#include "ssd.h"

/* From the board's devicetree. Zephyr does not manage this memory. */
#define BUFFER      DT_NODELABEL(ssd_buffer)
#define BUFFER_BASE ((uint8_t *)DT_REG_ADDR(BUFFER))
#define BUFFER_SIZE DT_REG_SIZE(BUFFER)

uint8_t *ssd_scratch(void)
{
	return BUFFER_BASE;
}

uint8_t *ssd_page_buffer(void)
{
	return BUFFER_BASE + NVME_HOST_PAGE;
}

void *ssd_buffer_after_a_page(uint32_t page_size, size_t *size)
{
	size_t used = NVME_HOST_PAGE + (size_t)page_size;

	*size = used < BUFFER_SIZE ? BUFFER_SIZE - used : 0;

	return BUFFER_BASE + used;
}
