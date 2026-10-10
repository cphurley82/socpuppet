/*
 * Zephyr's driver for the NVMe frontend of a socpuppet SSD. The registers
 * are in <socpuppet/regs/nvme_frontend.h>, which is generated from the
 * frontend's register map, and docs/models/nvme-frontend.md in socpuppet
 * says what they do. What firmware does with the driver is in
 * <socpuppet/drivers/nvme_frontend.h>.
 *
 * The frontend's interrupt is a level: its line is high for as long as a
 * status bit the firmware asked about is set. That is how nothing gets
 * lost, and it means the handler cannot return with the line still high.
 * It cannot see to what happened either: that is the firmware's work, in
 * a thread. So the handler tells the frontend not to interrupt for now,
 * and wakes the thread, and the thread asks to be interrupted again when
 * it has nothing left to see to.
 */

#define DT_DRV_COMPAT socpuppet_nvme_frontend

#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/sys_io.h>

#include <socpuppet/drivers/nvme_frontend.h>

/* Everything the status register can say, which is what can interrupt. */
#define ANYTHING (NVME_FRONTEND_ENABLED | NVME_FRONTEND_RESET | NVME_FRONTEND_COMMAND_WAITING)

struct nvme_frontend_config {
	mm_reg_t base;
	void (*connect_interrupt)(void);
};

struct nvme_frontend_data {
	/* Given by the interrupt handler when something has happened. */
	struct k_sem something_happened;
};

void nvme_frontend_get_limits(const struct device *dev, struct nvme_frontend_limits *limits)
{
	const struct nvme_frontend_config *config = dev->config;
	uint32_t both = sys_read32(config->base + NVME_FRONTEND_LIMITS);

	limits->io_queue_pairs = (both & NVME_FRONTEND_LIMITS_IO_QUEUE_PAIRS_MASK) >>
				 NVME_FRONTEND_LIMITS_IO_QUEUE_PAIRS_SHIFT;
	limits->vectors =
		(both & NVME_FRONTEND_LIMITS_VECTORS_MASK) >> NVME_FRONTEND_LIMITS_VECTORS_SHIFT;
}

uint32_t nvme_frontend_wait(const struct device *dev)
{
	const struct nvme_frontend_config *config = dev->config;
	struct nvme_frontend_data *data = dev->data;

	for (;;) {
		uint32_t happened = sys_read32(config->base + NVME_FRONTEND_STATUS) & ANYTHING;

		if (happened != 0) {
			return happened;
		}
		/*
		 * Nothing yet. If something happens between the look above
		 * and this write, the line is high as soon as it is written,
		 * and the handler runs before the thread can sleep.
		 */
		sys_write32(ANYTHING, config->base + NVME_FRONTEND_INTERRUPT_ENABLE);
		k_sem_take(&data->something_happened, K_FOREVER);
	}
}

static void nvme_frontend_isr(const struct device *dev)
{
	const struct nvme_frontend_config *config = dev->config;
	struct nvme_frontend_data *data = dev->data;

	sys_write32(0, config->base + NVME_FRONTEND_INTERRUPT_ENABLE);
	k_sem_give(&data->something_happened);
}

void nvme_frontend_acknowledge(const struct device *dev, uint32_t happened)
{
	const struct nvme_frontend_config *config = dev->config;

	sys_write32(happened, config->base + NVME_FRONTEND_STATUS);
}

void nvme_frontend_say_ready(const struct device *dev)
{
	const struct nvme_frontend_config *config = dev->config;

	sys_write32(NVME_FRONTEND_CONTROL_READY, config->base + NVME_FRONTEND_CONTROL);
}

uint16_t nvme_frontend_read_command(const struct device *dev,
				    uint8_t command[NVME_FRONTEND_COMMAND_SIZE])
{
	const struct nvme_frontend_config *config = dev->config;

	for (size_t at = 0; at < NVME_FRONTEND_COMMAND_SIZE; at += sizeof(uint32_t)) {
		uint32_t word = sys_read32(config->base + NVME_FRONTEND_COMMAND + at);

		memcpy(&command[at], &word, sizeof(word));
	}

	return (uint16_t)sys_read32(config->base + NVME_FRONTEND_COMMAND_QUEUE);
}

void nvme_frontend_post(const struct device *dev, uint16_t status, uint32_t result)
{
	const struct nvme_frontend_config *config = dev->config;

	sys_write32(result, config->base + NVME_FRONTEND_COMPLETION_RESULT);
	sys_write32(status, config->base + NVME_FRONTEND_COMPLETION_STATUS);
	sys_write32(NVME_FRONTEND_COMPLETION_POST_NOW,
		    config->base + NVME_FRONTEND_COMPLETION_POST);
}

void nvme_frontend_create_queue(const struct device *dev, const struct nvme_frontend_queue *queue)
{
	const struct nvme_frontend_config *config = dev->config;

	sys_write32(queue->id, config->base + NVME_FRONTEND_QUEUE_ID);
	sys_write32((uint32_t)queue->base, config->base + NVME_FRONTEND_QUEUE_BASE_LOW);
	sys_write32((uint32_t)(queue->base >> 32), config->base + NVME_FRONTEND_QUEUE_BASE_HIGH);
	sys_write32(queue->last_slot, config->base + NVME_FRONTEND_QUEUE_LAST);
	sys_write32(queue->link, config->base + NVME_FRONTEND_QUEUE_LINK);
	sys_write32(queue->kind, config->base + NVME_FRONTEND_QUEUE_CREATE);
}

static int nvme_frontend_init(const struct device *dev)
{
	const struct nvme_frontend_config *config = dev->config;
	struct nvme_frontend_data *data = dev->data;

	k_sem_init(&data->something_happened, 0, 1);
	/*
	 * The frontend interrupts for nothing until it is told to, which is
	 * when the firmware first waits: see nvme_frontend_wait().
	 */
	config->connect_interrupt();

	return 0;
}

#define NVME_FRONTEND_DEFINE(n)                                                                    \
	static void nvme_frontend_connect_interrupt##n(void)                                       \
	{                                                                                          \
		IRQ_CONNECT(DT_INST_IRQN(n), DT_INST_IRQ(n, priority), nvme_frontend_isr,          \
			    DEVICE_DT_INST_GET(n), 0);                                             \
		irq_enable(DT_INST_IRQN(n));                                                       \
	}                                                                                          \
	static const struct nvme_frontend_config nvme_frontend_config##n = {                       \
		.base = DT_INST_REG_ADDR(n),                                                       \
		.connect_interrupt = nvme_frontend_connect_interrupt##n,                           \
	};                                                                                         \
	static struct nvme_frontend_data nvme_frontend_data##n;                                    \
	DEVICE_DT_INST_DEFINE(n, nvme_frontend_init, NULL, &nvme_frontend_data##n,                 \
			      &nvme_frontend_config##n, POST_KERNEL,                               \
			      CONFIG_KERNEL_INIT_PRIORITY_DEVICE, NULL);

DT_INST_FOREACH_STATUS_OKAY(NVME_FRONTEND_DEFINE)
