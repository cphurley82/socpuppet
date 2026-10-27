/*
 * Zephyr's driver for a RISC-V IOMMU (riscv,iommu), the subset socpuppet's
 * has: a device directory, a first stage of Sv39 page tables, the command
 * and fault queues, and a wired interrupt.
 *
 * Everything the IOMMU reads is in memory the driver keeps: a directory of
 * one level, which is one page of 128 device contexts and so has room for
 * device IDs up to 127; the two queues, a page each; and a pool of pages
 * for page tables, which only grows. A change to a context or a page table
 * is followed by the command that says so and a fence, and the driver
 * waits until the IOMMU has run them, by polling its command queue's head.
 * That needs no kernel, so the driver works before the kernel is up, which
 * is when a bus's driver attaches its devices.
 *
 * The driver's functions are in <socpuppet/drivers/riscv_iommu.h>.
 */

#define DT_DRV_COMPAT riscv_iommu

#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include <socpuppet/drivers/riscv_iommu.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/barrier.h>
#include <zephyr/sys/sys_io.h>
#include <zephyr/sys/util.h>

BUILD_ASSERT(DT_NUM_INST_STATUS_OKAY(DT_DRV_COMPAT) == 1,
	     "socpuppet's driver for a RISC-V IOMMU drives one.");

/* The registers, by their offsets. */
#define CAPABILITIES 0x000
#define DDTP         0x010
#define CQB          0x018
#define CQH          0x020
#define CQT          0x024
#define FQB          0x028
#define FQH          0x030
#define FQT          0x034
#define CQCSR        0x048
#define FQCSR        0x04C
#define IPSR         0x054
#define ICVEC        0x2F8

/* capabilities: a first stage of Sv39, and wired interrupts. */
#define CAPABILITIES_SV39 BIT64(9)
#define CAPABILITIES_IGS  GENMASK64(29, 28)
#define IGS_WSI           1

/* ddtp: a directory of one level, and where its root table is. */
#define DDTP_ONE_LEVEL 2
#define DDTP_BUSY      BIT64(4)

/* A queue's base register and its control and status register: enabled, its
 * interrupt enabled, and on; and what software clears by writing it.
 */
#define QUEUE_ENABLE           BIT(0)
#define QUEUE_INTERRUPT_ENABLE BIT(1)
#define QUEUE_ON               BIT(16)
#define QUEUE_BUSY             BIT(17)
#define QUEUE_ERRORS           GENMASK(11, 8)

/* ipsr: the fault queue has something for software. */
#define IPSR_FIP BIT(1)

/* A page, and how much a page-table entry, a device context, a command and a
 * fault record take of it.
 */
#define PAGE            4096
#define CONTEXT_SIZE    32
#define COMMAND_SIZE    16
#define RECORD_SIZE     32
#define CONTEXTS        (PAGE / CONTEXT_SIZE)
#define COMMANDS        (PAGE / COMMAND_SIZE)
#define RECORDS         (PAGE / RECORD_SIZE)
/* A queue's LOG2SZ: one less than the log of its entries. */
#define LOG2SZ(entries) (LOG2(entries) - 1)

/* A device context's tc and fsc: valid, and a first stage of Sv39 from a
 * root table.
 */
#define TC_V     BIT64(0)
#define FSC_SV39 (8ULL << 60)
#define TC_WORD  0
#define FSC_WORD 3

/* A page-table entry: valid, readable, writable, for user mode (which a
 * device's access counts as), accessed and dirty; this IOMMU sets neither A
 * nor D itself.
 */
#define IOPTE_V    BIT64(0)
#define IOPTE_R    BIT64(1)
#define IOPTE_W    BIT64(2)
#define IOPTE_X    BIT64(3)
#define IOPTE_U    BIT64(4)
#define IOPTE_A    BIT64(6)
#define IOPTE_D    BIT64(7)
#define IOPTE_LEAF (IOPTE_R | IOPTE_W | IOPTE_X)

/* Sv39: three levels of 512 entries, a leaf at level 1 being 2 MiB. */
#define LEVELS   3
#define ENTRIES  512
#define MEGAPAGE (2 * 1024 * 1024)

/* The commands the driver sends. */
#define IOTINVAL_VMA    1
#define IOFENCE_C       2
#define IODIR_INVAL_DDT 3
#define IODIR_DV        BIT64(33)
#define IODIR_DID_SHIFT 40

/* A fault record's header: the cause in bits 11:0 and the device in 63:40. */
#define RECORD_CAUSE     GENMASK64(11, 0)
#define RECORD_DID_SHIFT 40

/* How long the driver waits for the IOMMU to run its commands, polling. */
#define POLLS   100000
#define POLL_US 1

struct riscv_iommu_config {
	uintptr_t base;
	void (*connect_irq)(void);
};

struct riscv_iommu_data {
	/* Where the IOMMU's command queue's tail is, as the driver last put it,
	 * and where the fault queue's head is, as it last read.
	 */
	uint32_t command_tail;
	uint32_t fault_head;
	/* How many of the pool's pages page tables have. */
	size_t pages_used;
	/* Each device's root page table, or none. */
	uint64_t *roots[CONTEXTS];
	/* Given by the interrupt for each fault record. */
	struct k_sem faults;
};

/* The directory's one table, the queues, and the pool for page tables. */
static uint64_t directory[PAGE / sizeof(uint64_t)] __aligned(PAGE);
static uint64_t commands[COMMANDS][COMMAND_SIZE / sizeof(uint64_t)] __aligned(PAGE);
static uint64_t records[RECORDS][RECORD_SIZE / sizeof(uint64_t)] __aligned(PAGE);
static uint64_t pool[CONFIG_SOCPUPPET_RISCV_IOMMU_PAGES][PAGE / sizeof(uint64_t)] __aligned(PAGE);

static uint64_t read64(const struct device *dev, uintptr_t offset)
{
	const struct riscv_iommu_config *config = dev->config;

	return sys_read64(config->base + offset);
}

static void write64(const struct device *dev, uintptr_t offset, uint64_t value)
{
	const struct riscv_iommu_config *config = dev->config;

	sys_write64(value, config->base + offset);
}

static uint32_t read32(const struct device *dev, uintptr_t offset)
{
	const struct riscv_iommu_config *config = dev->config;

	return sys_read32(config->base + offset);
}

static void write32(const struct device *dev, uintptr_t offset, uint32_t value)
{
	const struct riscv_iommu_config *config = dev->config;

	sys_write32(value, config->base + offset);
}

/* A page's number, which fsc holds in its low bits; and the same in bits
 * 53:10, where a base register, ddtp and a page-table entry hold it.
 */
static uint64_t ppn(uintptr_t page)
{
	return (uint64_t)page >> 12;
}

static uint64_t ppn_field(uintptr_t page)
{
	return ppn(page) << 10;
}

/* The page a page-table entry points at. */
static uint64_t *page_of(uint64_t entry)
{
	return (uint64_t *)(uintptr_t)((entry >> 10) << 12);
}

/* Polls the 32-bit register at `offset` until its bits in `mask` are `want`,
 * or the driver gives up. Returns 0 or -ETIMEDOUT.
 */
static int wait_for(const struct device *dev, uintptr_t offset, uint32_t mask, uint32_t want)
{
	for (int polls = 0; polls < POLLS; polls++) {
		if ((read32(dev, offset) & mask) == want) {
			return 0;
		}
		k_busy_wait(POLL_US);
	}
	return -ETIMEDOUT;
}

/* Puts a command in the command queue, for send_commands to start. */
static void queue_command(const struct device *dev, uint64_t first, uint64_t second)
{
	struct riscv_iommu_data *data = dev->data;

	commands[data->command_tail][0] = first;
	commands[data->command_tail][1] = second;
	data->command_tail = (data->command_tail + 1) % COMMANDS;
}

/* Has the IOMMU run what is queued, after a fence, and waits until it has:
 * the commands before the fence are done once the IOMMU is past it. Returns
 * 0; -EIO if the IOMMU stopped the queue at a command it does not have or
 * could not read, which it says in CQCSR; or -ETIMEDOUT.
 */
static int send_commands(const struct device *dev)
{
	struct riscv_iommu_data *data = dev->data;

	queue_command(dev, IOFENCE_C, 0);
	/* What the commands say has to be in memory before the IOMMU reads it. */
	barrier_dmem_fence_full();
	write32(dev, CQT, data->command_tail);
	for (int polls = 0; polls < POLLS; polls++) {
		if (read32(dev, CQH) == data->command_tail) {
			return 0;
		}
		if ((read32(dev, CQCSR) & QUEUE_ERRORS) != 0) {
			return -EIO;
		}
		k_busy_wait(POLL_US);
	}
	return -ETIMEDOUT;
}

/* The device context of `device_id`, in the directory's one table. */
static uint64_t *context_of(uint32_t device_id)
{
	return &directory[device_id * (CONTEXT_SIZE / sizeof(uint64_t))];
}

/* Writes a device's context, valid, with `fsc` its first stage, and says so. */
static int set_context(const struct device *dev, uint32_t device_id, uint64_t fsc)
{
	uint64_t *context = context_of(device_id);

	context[FSC_WORD] = fsc;
	/* The rest of the context is in place before it is valid. */
	barrier_dmem_fence_full();
	context[TC_WORD] = TC_V;
	queue_command(dev, IODIR_INVAL_DDT | IODIR_DV | ((uint64_t)device_id << IODIR_DID_SHIFT),
		      0);
	return send_commands(dev);
}

/* A page of the pool for a page table, empty, or NULL if none is left. */
static uint64_t *new_table(const struct device *dev)
{
	struct riscv_iommu_data *data = dev->data;
	uint64_t *table;

	if (data->pages_used == ARRAY_SIZE(pool)) {
		return NULL;
	}
	table = pool[data->pages_used++];
	memset(table, 0, PAGE);
	return table;
}

/* An address's index into the table at `level`, where 0 is the last. */
static size_t index_at(uintptr_t iova, int level)
{
	return (iova >> (12 + 9 * level)) % ENTRIES;
}

/* Finds the entry of the table at `level` that `iova` goes through, into
 * `*entry`, with a leaf above `level` split into the level below. With
 * `make`, every table above it is made if it is not there; without, a table
 * that is not there is -ENOENT. -ENOMEM if the pool ran out.
 */
static int entry_at(const struct device *dev, uint64_t *root, uintptr_t iova, int level, bool make,
		    uint64_t **entry)
{
	uint64_t *table = root;

	for (int at = LEVELS - 1; at > level; at--) {
		uint64_t *above = &table[index_at(iova, at)];

		if (!(*above & IOPTE_V) && !make) {
			return -ENOENT;
		}
		if (!(*above & IOPTE_V) || (*above & IOPTE_LEAF)) {
			uint64_t *below = new_table(dev);

			if (below == NULL) {
				return -ENOMEM;
			}
			if (*above & IOPTE_V) {
				/* A leaf that maps more than is asked for becomes a table
				 * of leaves that map the same, a level down.
				 */
				uint64_t step = 1ULL << (12 + 9 * (at - 1));

				for (size_t i = 0; i < ENTRIES; i++) {
					below[i] = *above + ((i * step) >> 2);
				}
			}
			barrier_dmem_fence_full();
			*above = ppn_field((uintptr_t)below) | IOPTE_V;
		}
		table = page_of(*above);
	}
	*entry = &table[index_at(iova, level)];
	return 0;
}

/* What a leaf allows, from `access`. */
static uint64_t leaf_flags(uint32_t access)
{
	return IOPTE_V | IOPTE_U | IOPTE_A | IOPTE_D | ((access & RISCV_IOMMU_READ) ? IOPTE_R : 0) |
	       ((access & RISCV_IOMMU_WRITE) ? IOPTE_W : 0);
}

int riscv_iommu_pass_through(const struct device *iommu, uint32_t device_id)
{
	if (device_id >= CONTEXTS) {
		return -EINVAL;
	}
	return set_context(iommu, device_id, 0);
}

int riscv_iommu_map(const struct device *iommu, uint32_t device_id, uintptr_t iova, uintptr_t pa,
		    size_t size, uint32_t access)
{
	struct riscv_iommu_data *data = iommu->data;
	uint64_t fsc;

	/* A page that allows nothing is not a page: an entry with neither R nor
	 * W is what Sv39 calls a pointer to the next table.
	 */
	if (device_id >= CONTEXTS || (iova | pa | size) % PAGE != 0 || access == 0 ||
	    (access & ~(RISCV_IOMMU_READ | RISCV_IOMMU_WRITE)) != 0) {
		return -EINVAL;
	}
	if (data->roots[device_id] == NULL) {
		data->roots[device_id] = new_table(iommu);
		if (data->roots[device_id] == NULL) {
			return -ENOMEM;
		}
	}
	for (size_t done = 0; done < size;) {
		/* 2 MiB at a time where both addresses and what is left allow. */
		bool mega =
			((iova + done) | (pa + done)) % MEGAPAGE == 0 && size - done >= MEGAPAGE;
		uint64_t *entry;
		int ret = entry_at(iommu, data->roots[device_id], iova + done, mega ? 1 : 0, true,
				   &entry);

		if (ret != 0) {
			return ret;
		}
		*entry = ppn_field(pa + done) | leaf_flags(access);
		done += mega ? MEGAPAGE : PAGE;
	}
	/* A device that was let through untranslated, or has had no page mapped,
	 * is pointed at its page tables; one that is already, is told they changed.
	 */
	fsc = FSC_SV39 | ppn((uintptr_t)data->roots[device_id]);
	if (context_of(device_id)[FSC_WORD] != fsc) {
		return set_context(iommu, device_id, fsc);
	}
	queue_command(iommu, IOTINVAL_VMA, 0);
	return send_commands(iommu);
}

int riscv_iommu_unmap(const struct device *iommu, uint32_t device_id, uintptr_t iova, size_t size)
{
	struct riscv_iommu_data *data = iommu->data;

	if (device_id >= CONTEXTS || data->roots[device_id] == NULL || (iova | size) % PAGE != 0) {
		return -EINVAL;
	}
	for (size_t done = 0; done < size; done += PAGE) {
		uint64_t *entry;
		int ret = entry_at(iommu, data->roots[device_id], iova + done, 0, false, &entry);

		/* A page no table leads to is not mapped, and needs no table made. */
		if (ret == -ENOENT) {
			continue;
		}
		if (ret != 0) {
			return ret;
		}
		*entry = 0;
	}
	queue_command(iommu, IOTINVAL_VMA, 0);
	return send_commands(iommu);
}

/* What a device's page tables map to itself, with the image built so: the
 * RAM, which is where a device's data is, and each IMSIC's page, which is
 * where its interrupt messages go.
 */
struct region {
	uintptr_t start;
	size_t size;
};

#define REGION_OF(node) {DT_REG_ADDR(node), ROUND_UP(DT_REG_SIZE(node), PAGE)},

static const struct region identity[] = {REGION_OF(DT_CHOSEN(zephyr_sram))
						 DT_FOREACH_STATUS_OKAY(riscv_imsic, REGION_OF)};

int riscv_iommu_attach(const struct device *iommu, uint32_t device_id)
{
	if (!IS_ENABLED(CONFIG_SOCPUPPET_RISCV_IOMMU_IDENTITY_PAGE_TABLE)) {
		return riscv_iommu_pass_through(iommu, device_id);
	}
	for (size_t i = 0; i < ARRAY_SIZE(identity); i++) {
		int ret = riscv_iommu_map(iommu, device_id, identity[i].start, identity[i].start,
					  identity[i].size, RISCV_IOMMU_READ | RISCV_IOMMU_WRITE);

		if (ret != 0) {
			return ret;
		}
	}
	return 0;
}

int riscv_iommu_take_fault(const struct device *iommu, struct riscv_iommu_fault *fault,
			   k_timeout_t timeout)
{
	struct riscv_iommu_data *data = iommu->data;

	while (read32(iommu, FQT) == data->fault_head) {
		if (k_sem_take(&data->faults, timeout) != 0) {
			return -EAGAIN;
		}
	}
	const uint64_t *record = records[data->fault_head];

	/* The record is in memory before the tail says so, and is read after. */
	barrier_dmem_fence_full();
	fault->cause = record[0] & RECORD_CAUSE;
	fault->device_id = record[0] >> RECORD_DID_SHIFT;
	fault->iova = record[2];
	data->fault_head = (data->fault_head + 1) % RECORDS;
	write32(iommu, FQH, data->fault_head);
	return 0;
}

static void riscv_iommu_isr(const struct device *dev)
{
	struct riscv_iommu_data *data = dev->data;

	write32(dev, IPSR, IPSR_FIP);
	k_sem_give(&data->faults);
}

/* Turns a queue on, with `enable` written to its control and status register
 * besides, and waits until it is.
 */
static int start_queue(const struct device *dev, uintptr_t base, uintptr_t csr, const void *queue,
		       unsigned int entries, uint32_t enable)
{
	write64(dev, base, ppn_field((uintptr_t)queue) | LOG2SZ(entries));
	write32(dev, csr, QUEUE_ENABLE | QUEUE_ERRORS | enable);
	return wait_for(dev, csr, QUEUE_ON | QUEUE_BUSY, QUEUE_ON);
}

static int riscv_iommu_init(const struct device *dev)
{
	const struct riscv_iommu_config *config = dev->config;
	struct riscv_iommu_data *data = dev->data;
	uint64_t capabilities = read64(dev, CAPABILITIES);
	int ret;

	if (!(capabilities & CAPABILITIES_SV39) ||
	    FIELD_GET(CAPABILITIES_IGS, capabilities) != IGS_WSI) {
		return -ENODEV;
	}
	k_sem_init(&data->faults, 0, K_SEM_MAX_LIMIT);

	/* Every cause on the one line. */
	write64(dev, ICVEC, 0);
	write32(dev, CQT, 0);
	write32(dev, FQH, 0);
	/* The driver polls the command queue, and only the fault queue interrupts. */
	ret = start_queue(dev, CQB, CQCSR, commands, COMMANDS, 0);
	if (ret == 0) {
		ret = start_queue(dev, FQB, FQCSR, records, RECORDS, QUEUE_INTERRUPT_ENABLE);
	}
	if (ret != 0) {
		return ret;
	}

	/* An empty directory: no device may do anything until it is attached. */
	write64(dev, DDTP, ppn_field((uintptr_t)directory) | DDTP_ONE_LEVEL);
	ret = wait_for(dev, DDTP, DDTP_BUSY, 0);
	if (ret != 0) {
		return ret;
	}

	config->connect_irq();
	return 0;
}

#define RISCV_IOMMU_INIT(n)                                                                        \
	static void riscv_iommu_connect_irq_##n(void)                                              \
	{                                                                                          \
		IRQ_CONNECT(DT_INST_IRQN(n), DT_INST_IRQ(n, priority), riscv_iommu_isr,            \
			    DEVICE_DT_INST_GET(n), 0);                                             \
		irq_enable(DT_INST_IRQN(n));                                                       \
	}                                                                                          \
	static struct riscv_iommu_data riscv_iommu_data_##n;                                       \
	static const struct riscv_iommu_config riscv_iommu_config_##n = {                          \
		.base = DT_INST_REG_ADDR(n),                                                       \
		.connect_irq = riscv_iommu_connect_irq_##n,                                        \
	};                                                                                         \
	DEVICE_DT_INST_DEFINE(n, riscv_iommu_init, NULL, &riscv_iommu_data_##n,                    \
			      &riscv_iommu_config_##n, PRE_KERNEL_1,                               \
			      CONFIG_SOCPUPPET_RISCV_IOMMU_INIT_PRIORITY, NULL);

DT_INST_FOREACH_STATUS_OKAY(RISCV_IOMMU_INIT)
