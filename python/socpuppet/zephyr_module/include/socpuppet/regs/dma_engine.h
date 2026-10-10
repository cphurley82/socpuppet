/*
 * DMA engine: the registers.
 *
 * Copies between the host's memory and the SSD's own, one copy for each
 * command.
 *
 * Generated from regs/dma_engine.rdl by tools/regs.py. Do not edit: change
 * the register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_DMA_ENGINE_H_
#define SOCPUPPET_REGS_DMA_ENGINE_H_

/* How many bytes of address space the block takes. */
#define DMA_ENGINE_SIZE 0x20U

/*
 * Write a command to start a copy of what the other registers say. Reads as
 * zero.
 */
#define DMA_ENGINE_COMMAND           0x00U
/* Copy from the host's memory into the SSD's own. */
#define DMA_ENGINE_COMMAND_FROM_HOST 1U
/* Copy from the SSD's own memory to the host's. */
#define DMA_ENGINE_COMMAND_TO_HOST   2U

/* How the last command went. Giving the next command forgets it. */
#define DMA_ENGINE_STATUS       0x04U
/* The command was carried out. */
#define DMA_ENGINE_STATUS_DONE  (1U << 0)
/* The command was not carried out, or not all of it. */
#define DMA_ENGINE_STATUS_ERROR (1U << 1)
/*
 * A command has been given and is not yet carried out. No other is taken
 * meanwhile.
 */
#define DMA_ENGINE_STATUS_BUSY  (1U << 2)

/* Which bits of `STATUS` raise the interrupt line while they are set. */
#define DMA_ENGINE_INTERRUPT_ENABLE       0x08U
#define DMA_ENGINE_INTERRUPT_ENABLE_DONE  (1U << 0)
#define DMA_ENGINE_INTERRUPT_ENABLE_ERROR (1U << 1)

/* Where in the host's memory, the low 32 bits. */
#define DMA_ENGINE_HOST_ADDRESS_LOW 0x0CU

/*
 * The high 32 bits. A host's memory can be above 4 GiB even when the SSD's
 * CPU is a 32-bit one.
 */
#define DMA_ENGINE_HOST_ADDRESS_HIGH 0x10U

/* Where in the SSD's own memory. */
#define DMA_ENGINE_LOCAL_ADDRESS 0x14U

/* How many bytes. */
#define DMA_ENGINE_LENGTH 0x18U

#endif /* SOCPUPPET_REGS_DMA_ENGINE_H_ */
