/*
 * The driver of the host's IOMMU, with the drive behind it.
 *
 * The IOMMU's driver has set the drive up before a test starts: the root
 * complex's driver asked it to, for the requester ID its node lists, and
 * this image asks for page tables that map every page of the RAM and the
 * IMSIC's to itself. So Zephyr's NVMe driver works as it would without an
 * IOMMU, and a test takes a page away to see what the IOMMU does.
 *
 * The drive is the one the shield `socpuppet_host_drive` describes, and
 * `socpuppet run` puts there: 🎭 a stand-in that answers as an NVMe drive
 * does, and fails a command whose data the host does not take.
 */

#include <stdint.h>
#include <string.h>

#include <socpuppet/drivers/riscv_iommu.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/kernel.h>
#include <zephyr/storage/disk_access.h>
#include <zephyr/toolchain.h>
#include <zephyr/ztest.h>

BUILD_ASSERT(IS_ENABLED(CONFIG_SHIELD_SOCPUPPET_HOST_IOMMU),
	     "Build this with -DSHIELD=\"socpuppet_host_drive;socpuppet_host_iommu\".");

#define ROOT_COMPLEX DT_NODELABEL(io_rc)
#define IOMMU        DT_PHANDLE(ROOT_COMPLEX, iommus)
/* The drive's requester ID, as the root complex's node gives it. */
#define DRIVE        DT_PHA(ROOT_COMPLEX, iommus, id)

#define DISK        "nvme0n0"
#define SECTOR_SIZE 512
#define PAGE_SIZE   4096
/* What the tests fill the buffer with beforehand, which a read changes:
 * nothing the stand-in drive holds is all of it.
 */
#define UNREAD      0xAA

/* A sector's worth of buffer, at the start of a page of its own, so that a
 * test can take its page away from the drive and nothing else's.
 */
static uint8_t buffer[PAGE_SIZE] __aligned(PAGE_SIZE);

static const struct device *const iommu = DEVICE_DT_GET(IOMMU);

static void *start_the_disk(void)
{
	zassert_ok(disk_access_init(DISK));

	return NULL;
}

static void fill_the_buffer(void *unused)
{
	ARG_UNUSED(unused);

	memset(buffer, UNREAD, sizeof(buffer));
}

/* Gives the drive the buffer's page back, after a test that took it away. */
static void give_the_page_back(void *unused)
{
	ARG_UNUSED(unused);

	(void)riscv_iommu_map(iommu, DRIVE, (uintptr_t)buffer, (uintptr_t)buffer, PAGE_SIZE,
			      RISCV_IOMMU_READ | RISCV_IOMMU_WRITE);
}

/* Whether the first sector's worth of the buffer is all `byte`. */
static bool the_buffer_is_all(uint8_t byte)
{
	for (size_t i = 0; i < SECTOR_SIZE; i++) {
		if (buffer[i] != byte) {
			return false;
		}
	}
	return true;
}

ZTEST(riscv_iommu, test_a_sector_read_through_the_drives_page_tables_lands)
{
	zassert_ok(disk_access_read(DISK, buffer, 0, 1));

	zassert_false(the_buffer_is_all(UNREAD));
}

ZTEST(riscv_iommu, test_a_read_into_a_page_the_drive_may_not_write_fails_and_is_reported)
{
	struct riscv_iommu_fault fault;

	zassert_ok(riscv_iommu_unmap(iommu, DRIVE, (uintptr_t)buffer, PAGE_SIZE));

	zassert_not_ok(disk_access_read(DISK, buffer, 0, 1));
	/* The IOMMU wrote its record as it refused the drive's write, before the
	 * drive failed the command.
	 */
	zassert_ok(riscv_iommu_take_fault(iommu, &fault, K_NO_WAIT));
	zassert_equal(fault.cause, RISCV_IOMMU_WRITE_PAGE_FAULT, "cause %u", fault.cause);
	zassert_equal(fault.device_id, DRIVE, "device %u", fault.device_id);
	zassert_equal(fault.iova, (uintptr_t)buffer, "address %llx",
		      (unsigned long long)fault.iova);
	zassert_true(the_buffer_is_all(UNREAD));
}

ZTEST_SUITE(riscv_iommu, NULL, start_the_disk, fill_the_buffer, give_the_page_back, NULL);
