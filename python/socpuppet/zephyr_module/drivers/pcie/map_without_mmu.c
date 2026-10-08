/*
 * k_mem_map_phys_bare() for a kernel with no MMU.
 *
 * The function gives a driver an address at which it can reach a device's
 * registers, given where they are in physical memory. With an MMU that
 * means writing a page table. Without one there is only physical memory,
 * and the address is the one the driver came with.
 *
 * Zephyr defines the function only for kernels with an MMU, and its MSI-X
 * code calls it whichever kind the kernel is, to reach a device's MSI-X
 * table. So an image with MSI-X and no MMU does not link without this. See
 * docs/upstream.md in socpuppet.
 */

#include <zephyr/kernel.h>
#include <zephyr/kernel/mm.h>

void k_mem_map_phys_bare(uint8_t **virt_ptr, uintptr_t phys, size_t size, uint32_t flags)
{
	ARG_UNUSED(size);
	ARG_UNUSED(flags);

	*virt_ptr = (uint8_t *)phys;
}
