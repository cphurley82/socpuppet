/*
 * The NVMe frontend of a socpuppet SSD, as the SSD's firmware uses it.
 *
 * The frontend is the hardware between the host and the firmware. It keeps
 * the host's queues: it fetches each command and holds it for the firmware,
 * one at a time, and it posts the completion the firmware gives it and
 * interrupts the host. The firmware makes the decisions: whether the
 * controller is ready, what a command means, and whether the host may have
 * the queue it asks for.
 *
 * What a firmware does with it, for ever:
 *
 *	uint32_t happened = nvme_frontend_wait(dev);
 *
 *	if (happened & NVME_FRONTEND_RESET) {
 *		... forget everything from before the reset ...
 *		nvme_frontend_acknowledge(dev, NVME_FRONTEND_RESET);
 *	}
 *	if (happened & NVME_FRONTEND_ENABLED) {
 *		nvme_frontend_acknowledge(dev, NVME_FRONTEND_ENABLED);
 *		nvme_frontend_say_ready(dev);
 *	}
 *	if (happened & NVME_FRONTEND_COMMAND_WAITING) {
 *		... nvme_frontend_read_command, do it, nvme_frontend_post ...
 *	}
 *
 * The reset comes first: what the host enabled is the controller as it is
 * after the reset. See docs/models/nvme-frontend.md in socpuppet.
 */

#ifndef SOCPUPPET_DRIVERS_NVME_FRONTEND_H_
#define SOCPUPPET_DRIVERS_NVME_FRONTEND_H_

#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/sys/util.h>

/* What nvme_frontend_wait() reports, one bit each. */
/* The host has enabled the controller. To be acknowledged. */
#define NVME_FRONTEND_ENABLED         BIT(0)
/* The host has reset the controller, by disabling it. To be acknowledged. */
#define NVME_FRONTEND_RESET           BIT(1)
/* A command is waiting. It stops waiting when its completion is posted. */
#define NVME_FRONTEND_COMMAND_WAITING BIT(2)

/* How long a command is. */
#define NVME_FRONTEND_COMMAND_SIZE 64

/* What the frontend has, which the firmware tells the host when asked. */
struct nvme_frontend_limits {
	/* How many pairs of I/O queues the host may have created. */
	uint16_t io_queue_pairs;
	/* How many interrupt vectors the frontend has for the host. */
	uint16_t vectors;
};

void nvme_frontend_get_limits(const struct device *dev, struct nvme_frontend_limits *limits);

/*
 * Sleeps until something has happened that the firmware has to see to, and
 * returns what, as NVME_FRONTEND_* bits. It returns at once if something
 * already has.
 */
uint32_t nvme_frontend_wait(const struct device *dev);

/*
 * Says that the firmware has seen to what it was told of: `happened` is
 * NVME_FRONTEND_ENABLED, NVME_FRONTEND_RESET, or both.
 *
 * Acknowledging a reset is a promise that the firmware holds nothing from
 * before it: no command it will still complete, and no queue it will still
 * ask for. Until then the frontend fetches no command, and drops what the
 * firmware does about the controller as it was.
 */
void nvme_frontend_acknowledge(const struct device *dev, uint32_t happened);

/*
 * Says that the firmware is ready for the host's commands. The host is
 * waiting for this after it has enabled the controller. The frontend only
 * hears it while the host has the controller enabled and no reset is
 * waiting to be acknowledged, and a reset takes it back.
 */
void nvme_frontend_say_ready(const struct device *dev);

/*
 * Reads the command that is waiting into `command`, and returns which
 * submission queue it came from. Queue 0 is the admin queue.
 */
uint16_t nvme_frontend_read_command(const struct device *dev,
				    uint8_t command[NVME_FRONTEND_COMMAND_SIZE]);

/*
 * Has the completion of the waiting command posted, which is what the host
 * is waiting for. `status` is how the command went: the status code in the
 * low byte, zero for success, and above it, in three bits, which list the
 * code is from. `result` is the command's answer, for the few that have
 * one. The frontend fills in the rest, and fetches the next command.
 */
void nvme_frontend_post(const struct device *dev, uint16_t status, uint32_t result);

/* The two kinds of queue. */
enum nvme_frontend_queue_kind {
	NVME_FRONTEND_COMPLETION_QUEUE = 1,
	NVME_FRONTEND_SUBMISSION_QUEUE = 2,
};

/* A queue the firmware has agreed that the host may have. */
struct nvme_frontend_queue {
	enum nvme_frontend_queue_kind kind;
	/* Its identifier, from 1 up. */
	uint16_t id;
	/* Where it is in the host's memory, and its last slot. */
	uint64_t base;
	uint16_t last_slot;
	/*
	 * What goes with it. For a completion queue, the interrupt vector that
	 * tells the host it has something to read. For a submission queue, the
	 * completion queue its commands' completions go to.
	 */
	uint16_t link;
};

/*
 * Has the frontend create a queue: from here on it takes the queue's
 * doorbell. The firmware has checked first that the host may have it. The
 * frontend refuses a queue it could not keep (one that exists, an
 * identifier or a vector it does not have, a submission queue whose
 * completion queue is missing), and a write it refuses is a bus fault.
 */
void nvme_frontend_create_queue(const struct device *dev, const struct nvme_frontend_queue *queue);

#endif /* SOCPUPPET_DRIVERS_NVME_FRONTEND_H_ */
