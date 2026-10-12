/*
 * The driver of the host's PCIe root complex, with a drive on the link.
 *
 * A controller driver has done its work by the time a test starts: Zephyr
 * scans the bus and places what it finds before the kernel is up, and its
 * NVMe driver has asked for its interrupts and spoken to the drive. So
 * these cases look at what was left behind, through Zephyr's own PCIe
 * calls, which go by way of the driver.
 *
 * The drive is the one the shield `socpuppet_host_drive` describes, and
 * `socpuppet run` puts there: 🎭 a stand-in that answers as an NVMe drive
 * does.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/pcie/controller.h>
#include <zephyr/drivers/pcie/pcie.h>
#include <zephyr/irq.h>
#include <zephyr/toolchain.h>
#include <zephyr/ztest.h>

BUILD_ASSERT(IS_ENABLED(CONFIG_SHIELD_SOCPUPPET_HOST_DRIVE),
	     "Build this with -DSHIELD=socpuppet_host_drive: the board alone has no PCIe link.");

#define ROOT_COMPLEX DT_NODELABEL(io_rc)
#define DRIVE        DT_NODELABEL(nvme0)

/* The memory window devices' registers are placed in, from the devicetree. */
#define WINDOW_START DT_RANGES_PARENT_BUS_ADDRESS_BY_IDX(ROOT_COMPLEX, 0)
#define WINDOW_SIZE  DT_RANGES_LENGTH_BY_IDX(ROOT_COMPLEX, 0)

#define DRIVES_ID PCIE_ID(DT_PROP(DRIVE, vendor_id), DT_PROP(DRIVE, device_id))

static const struct device *const root_complex = DEVICE_DT_GET(ROOT_COMPLEX);

/* What a scan of the bus found. */
static struct {
	unsigned int devices;
	bool has_the_drive;
	pcie_bdf_t drive;
} found;

static bool note_the_device(pcie_bdf_t bdf, pcie_id_t id, void *unused)
{
	ARG_UNUSED(unused);

	++found.devices;
	if (id == DRIVES_ID) {
		found.has_the_drive = true;
		found.drive = bdf;
	}

	/* Go on to the next function. */
	return true;
}

static void *scan_the_bus(void)
{
	const struct pcie_scan_opt every_function = {
		.cb = note_the_device,
	};

	zassert_ok(pcie_scan(&every_function));

	return NULL;
}

ZTEST(socpuppet_pcie, test_a_scan_finds_one_device_on_the_link_and_it_is_the_drive)
{
	zassert_equal(found.devices, 1, "%u devices", found.devices);
	zassert_true(found.has_the_drive);
}

ZTEST(socpuppet_pcie, test_the_drives_registers_are_placed_inside_the_memory_window)
{
	struct pcie_bar registers;

	zassert_true(pcie_get_mbar(found.drive, 0, &registers));
	zassert_true(registers.phys_addr >= WINDOW_START);
	zassert_true(registers.phys_addr + registers.size <= WINDOW_START + WINDOW_SIZE);
}

/*
 * The three cases below ask the driver for places in the window as Zephyr's
 * scan does when it finds a device's registers, through the same call. A
 * place once given is not taken back, which does a suite no harm: the
 * scan is long over.
 */

ZTEST(socpuppet_pcie, test_a_place_asked_for_after_another_is_past_it_at_a_multiple_of_its_size)
{
	const size_t small = 0x1000;
	const size_t large = 0x10000;
	uintptr_t first;
	uintptr_t second;

	zassert_true(
		pcie_ctrl_region_allocate(root_complex, found.drive, true, false, small, &first));
	zassert_true(
		pcie_ctrl_region_allocate(root_complex, found.drive, true, false, large, &second));

	zassert_true(second >= first + small);
	zassert_equal(second % large, 0, "it was put at 0x%lx", (unsigned long)second);
}

ZTEST(socpuppet_pcie, test_a_place_bigger_than_what_is_left_of_the_window_is_refused)
{
	uintptr_t unused;

	/* The whole window, of which the drive's registers have some already. */
	zassert_false(pcie_ctrl_region_allocate(root_complex, found.drive, true, false, WINDOW_SIZE,
						&unused));
}

ZTEST(socpuppet_pcie, test_a_place_in_io_space_is_refused)
{
	uintptr_t unused;

	/* The window is memory, and there is no other. */
	zassert_false(
		pcie_ctrl_region_allocate(root_complex, found.drive, false, false, 0x100, &unused));
}

ZTEST(socpuppet_pcie, test_the_identity_set_aside_for_the_drives_admin_queue_is_enabled)
{
	/*
	 * Zephyr's NVMe driver asks the controller driver for its vectors
	 * and enables the admin queue's, which is the first.
	 */
	zassert_true(irq_is_enabled(DT_PROP_BY_IDX(ROOT_COMPLEX, socpuppet_msi_identities, 0)));
}

ZTEST(socpuppet_pcie, test_zephyrs_nvme_driver_brought_the_drive_up_over_the_link)
{
	/*
	 * It has by now read the drive's registers where they were placed,
	 * which a drive answers at only once it is told to (memory
	 * decoding, which nothing else in Zephyr switches on for a drive),
	 * and had its first commands answered, each with an interrupt that
	 * came as a message.
	 */
	zassert_true(device_is_ready(DEVICE_DT_GET(DRIVE)));
}

ZTEST_SUITE(socpuppet_pcie, NULL, scan_the_bus, NULL, NULL, NULL);
