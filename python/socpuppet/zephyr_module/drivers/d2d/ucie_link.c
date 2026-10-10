/*
 * Zephyr's driver for one end of a socpuppet die-to-die link. The
 * registers are in docs/models/d2d-link.md in socpuppet, and what
 * firmware does with the driver is in <socpuppet/drivers/ucie_link.h>.
 *
 * Letting the other die out of reset is a register at the far end of the
 * link, so it is reached over the link's sideband, with the mailbox: fill
 * in what to do and where, trigger it, and wait for the answer. That is
 * what makes this end a reset controller, with the other die as its one
 * line.
 *
 * The link's interrupt is a level: its line is high for as long as the
 * status says it has changed, and that bit is cleared by writing a one
 * back to it. So the handler clears it, or it would be called again the
 * moment it returned, for ever. What the change was is still there to
 * read, in the bit that says whether the link is up, and what to do about
 * it is the firmware's business, in a thread: the handler wakes it.
 */

#define DT_DRV_COMPAT socpuppet_ucie_link

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/reset.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/sys_io.h>

#include <socpuppet/drivers/ucie_link.h>

/* UCIe's Link DVSEC, and the vendor block its register locator names. */
#define LINK_CONTROL            0x10
#define LINK_STATUS             0x14
#define LINK_EVENT_NOTIFICATION 0x18
#define DIE_RESET               0x24
/* The sideband mailbox, which reaches the other end's registers. */
#define MAILBOX_OPCODE          0x40
#define MAILBOX_ADDRESS         0x48
#define MAILBOX_DATA            0x50
#define MAILBOX_TRIGGER         0x58
#define MAILBOX_STATUS          0x5C

/* Link control: both bits are an action, and clear themselves. */
#define START_TRAINING           BIT(0)
#define RETRAIN_LINK             BIT(1)
/* Link status. */
#define LINK_UP                  BIT(0)
#define LINK_STATUS_CHANGED      BIT(2)
/* Link event notification. */
#define STATUS_CHANGED_INTERRUPT BIT(0)
/* The mailbox's status: how the last access went, and whether it is done. */
#define MAILBOX_STATUS_CODE      0x7
#define MAILBOX_BUSY             BIT(8)
#define MAILBOX_SUCCESS          0
#define MAILBOX_NO_REGISTER      2
/* What a sideband access can be. */
#define MEMORY_READ_32B          0x00
#define MEMORY_WRITE_32B         0x01

/*
 * How long the firmware waits for the link to come up. UCIe holds it in
 * reset for 4 ms, and training takes as long again as the link was built
 * to take; a link that cannot be trained gives up by itself after 8 ms in
 * a state nobody answers.
 */
#define LONG_ENOUGH_TO_TRAIN K_MSEC(100)
/*
 * How long the firmware waits for the other end to answer the mailbox, in
 * microseconds. A sideband access takes no time to speak of: what it
 * waits for is the two ends passing the packets between them.
 */
#define MAILBOX_PATIENCE_US  100000

struct ucie_link_config {
	mm_reg_t base;
	void (*connect_interrupt)(void);
};

struct ucie_link_data {
	/* Given by the interrupt handler when the link's status changes. */
	struct k_sem status_changed;
};

bool ucie_link_is_up(const struct device *dev)
{
	const struct ucie_link_config *config = dev->config;

	return (sys_read32(config->base + LINK_STATUS) & LINK_UP) != 0;
}

static int wait_until_up(const struct device *dev)
{
	struct ucie_link_data *data = dev->data;
	k_timepoint_t give_up = sys_timepoint_calc(LONG_ENOUGH_TO_TRAIN);

	/*
	 * A change that comes between the look and the sleep is not lost:
	 * the handler has given the semaphore by then, and the sleep ends at
	 * once.
	 */
	while (!ucie_link_is_up(dev)) {
		if (k_sem_take(&data->status_changed, sys_timepoint_timeout(give_up)) != 0) {
			return -ETIMEDOUT;
		}
	}

	return 0;
}

void ucie_link_wait_until_down(const struct device *dev)
{
	struct ucie_link_data *data = dev->data;

	while (ucie_link_is_up(dev)) {
		k_sem_take(&data->status_changed, K_FOREVER);
	}
}

/* Tells the link what to do, and waits for it to be up. */
static int train(const struct device *dev, uint32_t how)
{
	const struct ucie_link_config *config = dev->config;

	sys_write32(how, config->base + LINK_CONTROL);

	return wait_until_up(dev);
}

int ucie_link_train(const struct device *dev)
{
	return train(dev, START_TRAINING);
}

int ucie_link_retrain(const struct device *dev)
{
	return train(dev, RETRAIN_LINK);
}

/*
 * Writes one register at the other end of the link, through the mailbox:
 * what to do, where and with what, then the trigger, then the answer.
 */
static int write_at_the_other_end(const struct device *dev, uint32_t address, uint32_t value)
{
	const struct ucie_link_config *config = dev->config;
	uint32_t status;

	sys_write32(MEMORY_WRITE_32B, config->base + MAILBOX_OPCODE);
	sys_write32(address, config->base + MAILBOX_ADDRESS);
	sys_write32(value, config->base + MAILBOX_DATA);
	sys_write32(1, config->base + MAILBOX_TRIGGER);

	if (!WAIT_FOR(((status = sys_read32(config->base + MAILBOX_STATUS)) & MAILBOX_BUSY) == 0,
		      MAILBOX_PATIENCE_US,
		      /* and asks again at once */)) {
		return -ETIMEDOUT;
	}

	return (status & MAILBOX_STATUS_CODE) == MAILBOX_SUCCESS ? 0 : -EIO;
}

/*
 * The reset API. The one line is the other die, and the register that
 * holds it is at the other end of the link: a zero there lets it go.
 * Letting it go is all a manager does with it, so that is all there is.
 */
static int ucie_link_line_deassert(const struct device *dev, uint32_t id)
{
	if (id != UCIE_LINK_THE_OTHER_DIE) {
		return -EINVAL;
	}

	return write_at_the_other_end(dev, DIE_RESET, 0);
}

static DEVICE_API(reset, ucie_link_api) = {
	.line_deassert = ucie_link_line_deassert,
};

static void ucie_link_isr(const struct device *dev)
{
	const struct ucie_link_config *config = dev->config;
	struct ucie_link_data *data = dev->data;

	sys_write32(LINK_STATUS_CHANGED, config->base + LINK_STATUS);
	k_sem_give(&data->status_changed);
}

static int ucie_link_init(const struct device *dev)
{
	const struct ucie_link_config *config = dev->config;
	struct ucie_link_data *data = dev->data;

	k_sem_init(&data->status_changed, 0, 1);
	config->connect_interrupt();
	/* The handler never masks the interrupt, so asking once is enough. */
	sys_write32(STATUS_CHANGED_INTERRUPT, config->base + LINK_EVENT_NOTIFICATION);

	return 0;
}

#define UCIE_LINK_DEFINE(n)                                                                        \
	static void ucie_link_connect_interrupt##n(void)                                           \
	{                                                                                          \
		IRQ_CONNECT(DT_INST_IRQN(n), DT_INST_IRQ(n, priority), ucie_link_isr,              \
			    DEVICE_DT_INST_GET(n), 0);                                             \
		irq_enable(DT_INST_IRQN(n));                                                       \
	}                                                                                          \
	static const struct ucie_link_config ucie_link_config##n = {                               \
		.base = DT_INST_REG_ADDR(n),                                                       \
		.connect_interrupt = ucie_link_connect_interrupt##n,                               \
	};                                                                                         \
	static struct ucie_link_data ucie_link_data##n;                                            \
	DEVICE_DT_INST_DEFINE(n, ucie_link_init, NULL, &ucie_link_data##n, &ucie_link_config##n,   \
			      POST_KERNEL, CONFIG_RESET_INIT_PRIORITY, &ucie_link_api);

DT_INST_FOREACH_STATUS_OKAY(UCIE_LINK_DEFINE)
