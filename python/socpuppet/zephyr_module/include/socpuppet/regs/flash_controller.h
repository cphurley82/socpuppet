/*
 * Flash controller: the registers.
 *
 * Moves a page between the NAND flash chip and the SSD's own memory, or
 * erases a block, one command at a time.
 *
 * Generated from regs/flash_controller.rdl by tools/regs.py. Do not edit:
 * change the register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_FLASH_CONTROLLER_H_
#define SOCPUPPET_REGS_FLASH_CONTROLLER_H_

/* How many bytes of address space the block takes. */
#define FLASH_CONTROLLER_SIZE 0x30U

/*
 * Write a command to have it carried out on what the other registers say.
 * Reads as zero.
 */
#define FLASH_CONTROLLER_COMMAND              0x00U
/* Read a page of the chip into the SSD's own memory. */
#define FLASH_CONTROLLER_COMMAND_READ_PAGE    1U
/* Program a page of the chip from the SSD's own memory. */
#define FLASH_CONTROLLER_COMMAND_PROGRAM_PAGE 2U
/* Erase a block of the chip. */
#define FLASH_CONTROLLER_COMMAND_ERASE_BLOCK  3U
/*
 * Ask the chip what it is. `PAGE_SIZE`, `PAGES_PER_BLOCK` and `BLOCKS` read
 * as zero until this has been done.
 */
#define FLASH_CONTROLLER_COMMAND_IDENTIFY     4U

/* How the last command went. Giving the next command forgets it. */
#define FLASH_CONTROLLER_STATUS       0x04U
/* The command was carried out. */
#define FLASH_CONTROLLER_STATUS_DONE  (1U << 0)
/* The command was not carried out, or not all of it. */
#define FLASH_CONTROLLER_STATUS_ERROR (1U << 1)
/*
 * A command has been given and is not yet carried out. No other is taken
 * meanwhile.
 */
#define FLASH_CONTROLLER_STATUS_BUSY  (1U << 2)

/* Which bits of `STATUS` raise the interrupt line while they are set. */
#define FLASH_CONTROLLER_INTERRUPT_ENABLE       0x08U
#define FLASH_CONTROLLER_INTERRUPT_ENABLE_DONE  (1U << 0)
#define FLASH_CONTROLLER_INTERRUPT_ENABLE_ERROR (1U << 1)

/* Which block of the chip. */
#define FLASH_CONTROLLER_BLOCK 0x0CU

/* Which page of that block. */
#define FLASH_CONTROLLER_PAGE 0x10U

/* Where the page is, or goes, in the SSD's own memory. */
#define FLASH_CONTROLLER_LOCAL_ADDRESS 0x14U

/* How big a page of the chip is, in bytes. */
#define FLASH_CONTROLLER_PAGE_SIZE 0x20U

/* How many pages make a block. */
#define FLASH_CONTROLLER_PAGES_PER_BLOCK 0x24U

/* How many blocks the chip has. */
#define FLASH_CONTROLLER_BLOCKS 0x28U

#endif /* SOCPUPPET_REGS_FLASH_CONTROLLER_H_ */
