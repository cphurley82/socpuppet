/*
 * A RISC-V IOMMU: what stands between devices and memory, so that each
 * device reaches only the memory it was given.
 *
 * Every address a device uses goes through page tables its driver owns,
 * found by the device's ID, which for a PCIe device is its requester ID.
 * An access that is not mapped is refused, and the IOMMU writes a fault
 * record for software to read. Zephyr has no IOMMU subsystem, so these are
 * the driver's own functions.
 *
 * A device is let through untranslated (riscv_iommu_pass_through), or
 * given page tables of its own, from the first page mapped for it
 * (riscv_iommu_map). A bus's driver attaches each device behind the IOMMU
 * before the device does anything (riscv_iommu_attach), which is one or
 * the other as the image is built: the choice
 * CONFIG_SOCPUPPET_RISCV_IOMMU_BOOT_POLICY.
 */

#ifndef SOCPUPPET_DRIVERS_RISCV_IOMMU_H_
#define SOCPUPPET_DRIVERS_RISCV_IOMMU_H_

#include <stddef.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

/* What a device may do in a page it is given. */
#define RISCV_IOMMU_READ  BIT(0)
#define RISCV_IOMMU_WRITE BIT(1)

/* Why the IOMMU refused an access, as a fault record says: a write to a page
 * whose entry does not allow it.
 */
#define RISCV_IOMMU_WRITE_PAGE_FAULT 15

/* What a fault record says. */
struct riscv_iommu_fault {
	/* Why: the specification's cause, such as RISCV_IOMMU_WRITE_PAGE_FAULT. */
	uint16_t cause;
	/* Which device: the ID the IOMMU knows it by. */
	uint32_t device_id;
	/* The address the device used. */
	uint64_t iova;
};

/*
 * Lets the device `device_id` through as the image is built to: untranslated,
 * or through page tables that map every page of the RAM and of each IMSIC to
 * itself. What a bus's driver calls for each device behind the IOMMU before
 * the device does anything. Returns 0, or -EINVAL for an ID the IOMMU has
 * no room for, or -ENOMEM if the driver has no page left for the tables.
 */
int riscv_iommu_attach(const struct device *iommu, uint32_t device_id);

/* Lets the device `device_id` through untranslated. */
int riscv_iommu_pass_through(const struct device *iommu, uint32_t device_id);

/*
 * Maps `size` bytes at `iova`, as the device `device_id` sees them, to `pa`,
 * for it to do what `access` says, a mask of RISCV_IOMMU_READ and
 * RISCV_IOMMU_WRITE. All three are whole pages of 4 KiB. The device's
 * accesses go through its page tables from then on, and the first map for a
 * device gives it them. Returns 0, -EINVAL, or -ENOMEM if the driver has no
 * page left for the tables.
 */
int riscv_iommu_map(const struct device *iommu, uint32_t device_id, uintptr_t iova, uintptr_t pa,
		    size_t size, uint32_t access);

/* Takes away what riscv_iommu_map gave, page by page. */
int riscv_iommu_unmap(const struct device *iommu, uint32_t device_id, uintptr_t iova, size_t size);

/*
 * Takes the oldest fault record from the IOMMU's fault queue into `fault`,
 * waiting up to `timeout` for one. Returns 0, or -EAGAIN if none came.
 */
int riscv_iommu_take_fault(const struct device *iommu, struct riscv_iommu_fault *fault,
			   k_timeout_t timeout);

#endif /* SOCPUPPET_DRIVERS_RISCV_IOMMU_H_ */
