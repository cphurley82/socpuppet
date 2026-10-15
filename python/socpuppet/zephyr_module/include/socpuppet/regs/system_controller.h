/*
 * System controller: the registers.
 *
 * What a CPU asks about itself and its last reset, and the registers that
 * reset it and switch it off.
 *
 * Generated from regs/system_controller.rdl by tools/regs.py. Do not edit:
 * change the register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_SYSTEM_CONTROLLER_H_
#define SOCPUPPET_REGS_SYSTEM_CONTROLLER_H_

/* How many bytes of address space the block takes. */
#define SYSTEM_CONTROLLER_SIZE 0x20U

/* Which die the CPU is on, as the number the board gave it. */
#define SYSTEM_CONTROLLER_DIE 0x00U

/*
 * Where the CPU's boot ROM finds the image to start: the address of the
 * image's header.
 */
#define SYSTEM_CONTROLLER_BOOT_ADDRESS 0x04U

/* Why the CPU was last reset. */
#define SYSTEM_CONTROLLER_RESET_CAUSE          0x08U
/* The power came on, and nothing has reset the CPU since. */
#define SYSTEM_CONTROLLER_RESET_CAUSE_POWER_ON 0U
/* The watchdog bit: firmware stopped feeding it. */
#define SYSTEM_CONTROLLER_RESET_CAUSE_WATCHDOG 1U
/* Firmware asked, by writing to `RESET_REQUEST`. */
#define SYSTEM_CONTROLLER_RESET_CAUSE_SOFTWARE 2U

/* Asks for a reset of the CPU. Reads as zero. */
#define SYSTEM_CONTROLLER_RESET_REQUEST       0x0CU
/* Write a one to reset the CPU. */
#define SYSTEM_CONTROLLER_RESET_REQUEST_RESET (1U << 0)

/*
 * Switches the CPU off: holds it in reset for good. Reads as one once it has
 * been.
 */
#define SYSTEM_CONTROLLER_POWER_OFF     0x10U
/* Write a one to switch the CPU off. A zero changes nothing. */
#define SYSTEM_CONTROLLER_POWER_OFF_OFF (1U << 0)

#endif /* SOCPUPPET_REGS_SYSTEM_CONTROLLER_H_ */
