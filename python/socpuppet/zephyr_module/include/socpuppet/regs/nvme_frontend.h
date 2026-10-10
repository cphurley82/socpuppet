/*
 * NVMe frontend: the registers.
 *
 * The CPU's side of the frontend: what the host has done, the command that is
 * waiting, how it went, and the queues the firmware has agreed to.
 *
 * Generated from regs/nvme_frontend.rdl by tools/regs.py. Do not edit: change
 * the register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_NVME_FRONTEND_H_
#define SOCPUPPET_REGS_NVME_FRONTEND_H_

/* How many bytes of address space the block takes. */
#define NVME_FRONTEND_SIZE 0x80U

/* What the firmware says of itself. */
#define NVME_FRONTEND_CONTROL       0x00U
/*
 * The firmware is ready for the host's commands. The host sees it as
 * `CSTS.RDY`.
 */
#define NVME_FRONTEND_CONTROL_READY (1U << 0)

/* What the host has done, and whether a command is waiting. */
#define NVME_FRONTEND_STATUS                 0x04U
/* The host has enabled the controller. */
#define NVME_FRONTEND_STATUS_ENABLED         (1U << 0)
/*
 * The host has disabled the controller, which is a reset. Writing the one
 * says the firmware holds nothing from before it.
 */
#define NVME_FRONTEND_STATUS_DISABLED        (1U << 1)
/* A command is waiting. Set for exactly as long as one is. */
#define NVME_FRONTEND_STATUS_COMMAND_WAITING (1U << 2)

/* Which bits of `STATUS` raise `cpu_irq` while they are set. */
#define NVME_FRONTEND_INTERRUPT_ENABLE                 0x08U
#define NVME_FRONTEND_INTERRUPT_ENABLE_ENABLED         (1U << 0)
#define NVME_FRONTEND_INTERRUPT_ENABLE_DISABLED        (1U << 1)
#define NVME_FRONTEND_INTERRUPT_ENABLE_COMMAND_WAITING (1U << 2)

/* What the frontend has, for the firmware to tell the host. */
#define NVME_FRONTEND_LIMITS                      0x0CU
/* How many pairs of I/O queues, which is eight. */
#define NVME_FRONTEND_LIMITS_IO_QUEUE_PAIRS_MASK  0x0000FFFFU
#define NVME_FRONTEND_LIMITS_IO_QUEUE_PAIRS_SHIFT 0U
/* How many interrupt vectors it has for the host. */
#define NVME_FRONTEND_LIMITS_VECTORS_MASK         0xFFFF0000U
#define NVME_FRONTEND_LIMITS_VECTORS_SHIFT        16U

/*
 * Which submission queue the waiting command came from. 0 is the admin queue.
 */
#define NVME_FRONTEND_COMMAND_QUEUE 0x10U

/*
 * The first 32 bits of the completion: the command's answer, for the few that
 * have one.
 */
#define NVME_FRONTEND_COMPLETION_RESULT 0x14U

/*
 * How the command went, laid out as the status field of a completion is, less
 * the phase bit. The other bits read back as zero.
 */
#define NVME_FRONTEND_COMPLETION_STATUS            0x18U
/* The status code, zero for success. */
#define NVME_FRONTEND_COMPLETION_STATUS_CODE_MASK  0x000000FFU
#define NVME_FRONTEND_COMPLETION_STATUS_CODE_SHIFT 0U
/* Which list of codes that is from. */
#define NVME_FRONTEND_COMPLETION_STATUS_TYPE_MASK  0x00000700U
#define NVME_FRONTEND_COMPLETION_STATUS_TYPE_SHIFT 8U

/* Has the completion of the waiting command posted. Reads as zero. */
#define NVME_FRONTEND_COMPLETION_POST     0x1CU
/* Write a one, and nothing else, to post it. */
#define NVME_FRONTEND_COMPLETION_POST_NOW (1U << 0)

/* A queue to create: which, */
#define NVME_FRONTEND_QUEUE_ID 0x20U

/* where it is in the host's memory, the low 32 bits, */
#define NVME_FRONTEND_QUEUE_BASE_LOW 0x24U

/* and the high 32 bits, */
#define NVME_FRONTEND_QUEUE_BASE_HIGH 0x28U

/* its last slot, which is its size less one, */
#define NVME_FRONTEND_QUEUE_LAST 0x2CU

/*
 * and what goes with it: a completion queue's interrupt vector, or the
 * completion queue a submission queue's completions go to.
 */
#define NVME_FRONTEND_QUEUE_LINK 0x30U

/* Write which kind of queue to create it. Reads as zero. */
#define NVME_FRONTEND_QUEUE_CREATE                  0x34U
/* Create the completion queue the queue registers describe. */
#define NVME_FRONTEND_QUEUE_CREATE_COMPLETION_QUEUE 1U
/* Create the submission queue they describe. */
#define NVME_FRONTEND_QUEUE_CREATE_SUBMISSION_QUEUE 2U

/*
 * The waiting command, 64 bytes, read whole or a piece at a time. Zeros when
 * none is waiting.
 */
#define NVME_FRONTEND_COMMAND      0x40U
#define NVME_FRONTEND_COMMAND_SIZE 0x40U

#endif /* SOCPUPPET_REGS_NVME_FRONTEND_H_ */
