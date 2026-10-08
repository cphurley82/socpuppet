/*
 * Zephyr's driver for the PCIe root complex of a socpuppet platform.
 *
 * Zephyr's own PCIe code does the work: it scans the bus, sizes each
 * device's base address registers (BARs) and gives them addresses. A
 * controller driver tells it three things about the hardware, and this is
 * the one for a socpuppet platform.
 *
 *   - How to reach a device's configuration space. Here that is the
 *     configuration window (ECAM), laid out the standard way.
 *   - Where a device's registers may be placed. Here that is one memory
 *     window, in which an address on the PCIe bus is the CPU's address.
 *     That is what Zephyr takes it for unless a driver says otherwise, so
 *     this one says nothing.
 *   - Where a device is to send its interrupt messages (MSI), and which
 *     interrupt each one arrives as. Here they go to the MSI-to-PLIC bridge
 *     that the node's `msi-parent` names, which pulses one PLIC source for
 *     each vector.
 *
 * Zephyr's generic ECAM driver (pcie_ecam.c) does the first two. It can
 * only deliver MSI through an Arm GICv3 ITS, which is why this is a driver
 * of its own. See docs/upstream.md in socpuppet.
 */

#define DT_DRV_COMPAT socpuppet_pcie

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/pcie/controller.h>
#include <zephyr/drivers/pcie/pcie.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

struct socpuppet_pcie_data {
	/* How much of the memory window has been given to devices. */
	size_t allocated;
};

static uint32_t socpuppet_pcie_conf_read(const struct device *dev, pcie_bdf_t bdf,
					 unsigned int reg)
{
	const struct pcie_ctrl_config *config = dev->config;

	return pcie_generic_ctrl_conf_read(config->cfg_addr, bdf, reg);
}

static void socpuppet_pcie_conf_write(const struct device *dev, pcie_bdf_t bdf, unsigned int reg,
				      uint32_t data)
{
	const struct pcie_ctrl_config *config = dev->config;

	pcie_generic_ctrl_conf_write(config->cfg_addr, bdf, reg, data);
}

/*
 * Gives a BAR of `bar_size` bytes the next free place in the memory
 * window. A BAR's size is a power of two, and its address a multiple of
 * its size. There is no I/O space.
 */
static bool socpuppet_pcie_region_allocate(const struct device *dev, pcie_bdf_t bdf, bool mem,
					   bool mem64, size_t bar_size, uintptr_t *bar_bus_addr)
{
	const struct pcie_ctrl_config *config = dev->config;
	struct socpuppet_pcie_data *data = dev->data;
	uintptr_t start = config->ranges[0].pcie_bus_addr;
	uintptr_t addr = ROUND_UP(start + data->allocated, bar_size);

	ARG_UNUSED(bdf);
	ARG_UNUSED(mem64);

	if (!mem || addr + bar_size > start + config->ranges[0].map_length) {
		return false;
	}

	data->allocated = addr + bar_size - start;
	*bar_bus_addr = addr;

	return true;
}

/*
 * Zephyr asks this when it finds a bridge, for where the bus behind the
 * bridge may start. A socpuppet platform has no bridges: one device sits
 * on the link.
 */
static bool socpuppet_pcie_region_get_allocate_base(const struct device *dev, pcie_bdf_t bdf,
						    bool mem, bool mem64, size_t align,
						    uintptr_t *bar_base_addr)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(bdf);
	ARG_UNUSED(mem);
	ARG_UNUSED(mem64);
	ARG_UNUSED(align);
	ARG_UNUSED(bar_base_addr);

	return false;
}

#ifdef CONFIG_PCIE_MSI

/*
 * The bridge. Zephyr has one PCIe controller, the one `chosen` names, so
 * there is one of these nodes and one bridge to find.
 */
#define MSI_BRIDGE DT_INST_PHANDLE(0, msi_parent)

#define MSI_BRIDGE_IRQ(vector, _) DT_IRQN_BY_IDX(MSI_BRIDGE, vector)

/* The interrupt each of the bridge's vectors arrives as: its PLIC source. */
static const unsigned int msi_bridge_irqs[] = {
	LISTIFY(DT_NUM_IRQS(MSI_BRIDGE), MSI_BRIDGE_IRQ, (,))
};

/*
 * Says, for each of a device's interrupt vectors, what the device is to
 * write and where, and which interrupt that arrives as. The message is the
 * vector's own number, written to the bridge's register.
 *
 * The device's vector N gets the bridge's vector N. With one device on
 * the link there is no one to share the bridge with.
 */
static uint8_t socpuppet_pcie_msi_device_setup(const struct device *dev, unsigned int priority,
					       msi_vector_t *vectors, uint8_t n_vector)
{
	uint8_t count = MIN(n_vector, ARRAY_SIZE(msi_bridge_irqs));

	ARG_UNUSED(dev);

	for (uint8_t vector = 0; vector < count; vector++) {
		vectors[vector].arch.irq = msi_bridge_irqs[vector];
		vectors[vector].arch.address = DT_REG_ADDR(MSI_BRIDGE);
		vectors[vector].arch.eventid = vector;
		vectors[vector].arch.priority = priority;
	}

	return count;
}

#endif /* CONFIG_PCIE_MSI */

/*
 * Switches on memory decoding in a function, which is what makes it answer
 * at the addresses its BARs were just given.
 *
 * Zephyr's scan sets the bit for bridges only, and its NVMe driver does
 * not set it for itself: on a PC the firmware has done it before Zephyr
 * starts. Here this driver is that firmware. See docs/upstream.md in
 * socpuppet.
 */
static bool socpuppet_pcie_enable_memory_decoding(pcie_bdf_t bdf, pcie_id_t id, void *unused)
{
	ARG_UNUSED(id);
	ARG_UNUSED(unused);

	pcie_set_cmd(bdf, PCIE_CONF_CMDSTAT_MEM, true);

	/* Go on to the next function. */
	return true;
}

static int socpuppet_pcie_init(const struct device *dev)
{
	const struct pcie_scan_opt every_function = {
		.cb = socpuppet_pcie_enable_memory_decoding,
	};

	pcie_generic_ctrl_enumerate(dev, PCIE_BDF(0, 0, 0));
	pcie_scan(&every_function);

	return 0;
}

static DEVICE_API(pcie_ctrl, socpuppet_pcie_api) = {
	.conf_read = socpuppet_pcie_conf_read,
	.conf_write = socpuppet_pcie_conf_write,
	.region_allocate = socpuppet_pcie_region_allocate,
	.region_get_allocate_base = socpuppet_pcie_region_get_allocate_base,
#ifdef CONFIG_PCIE_MSI
	.msi_device_setup = socpuppet_pcie_msi_device_setup,
#endif
};

#define SOCPUPPET_PCIE_INIT(n)                                                                    \
	static struct socpuppet_pcie_data socpuppet_pcie_data##n;                                  \
	static const struct pcie_ctrl_config socpuppet_pcie_config##n = {                          \
		.cfg_addr = DT_INST_REG_ADDR(n),                                                   \
		.cfg_size = DT_INST_REG_SIZE(n),                                                   \
		.ranges_count = DT_NUM_RANGES(DT_DRV_INST(n)),                                     \
		.ranges = {DT_FOREACH_RANGE(DT_DRV_INST(n), PCIE_RANGE_FORMAT)},                   \
	};                                                                                         \
	BUILD_ASSERT(DT_NUM_RANGES(DT_DRV_INST(n)) == 1,                                           \
		     "A socpuppet,pcie node has one range: its memory window.");                   \
	DEVICE_DT_INST_DEFINE(n, &socpuppet_pcie_init, NULL, &socpuppet_pcie_data##n,              \
			      &socpuppet_pcie_config##n, PRE_KERNEL_1, CONFIG_PCIE_INIT_PRIORITY,  \
			      &socpuppet_pcie_api);

DT_INST_FOREACH_STATUS_OKAY(SOCPUPPET_PCIE_INIT)
