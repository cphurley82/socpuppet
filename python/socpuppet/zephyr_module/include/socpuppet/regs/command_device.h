/*
 * Command device: the registers.
 *
 * The three registers of any device its CPU gives one command at a time.
 *
 * Generated from regs/command_device.rdl by tools/regs.py. Do not edit:
 * change the register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_COMMAND_DEVICE_H_
#define SOCPUPPET_REGS_COMMAND_DEVICE_H_

/* How many bytes of address space the block takes. */
#define COMMAND_DEVICE_SIZE 0x0CU

/* Write a command to have it carried out. Reads as zero. */
#define COMMAND_DEVICE_COMMAND 0x00U

/* How the last command went. Giving the next command forgets it. */
#define COMMAND_DEVICE_STATUS       0x04U
/* The command was carried out. */
#define COMMAND_DEVICE_STATUS_DONE  (1U << 0)
/* The command was not carried out, or not all of it. */
#define COMMAND_DEVICE_STATUS_ERROR (1U << 1)
/*
 * A command has been given and is not yet carried out. No other is taken
 * meanwhile.
 */
#define COMMAND_DEVICE_STATUS_BUSY  (1U << 2)

/* Which bits of `STATUS` raise the interrupt line while they are set. */
#define COMMAND_DEVICE_INTERRUPT_ENABLE       0x08U
#define COMMAND_DEVICE_INTERRUPT_ENABLE_DONE  (1U << 0)
#define COMMAND_DEVICE_INTERRUPT_ENABLE_ERROR (1U << 1)

#endif /* SOCPUPPET_REGS_COMMAND_DEVICE_H_ */
