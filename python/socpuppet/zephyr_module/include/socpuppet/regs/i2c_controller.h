/*
 * I2C controller: the registers.
 *
 * A controller on an I2C bus: it starts and stops transfers, and sends and
 * receives one byte at a time.
 *
 * Generated from regs/i2c_controller.rdl by tools/regs.py. Do not edit:
 * change the register map and run `uv run python tools/lint.py --fix`.
 */

#ifndef SOCPUPPET_REGS_I2C_CONTROLLER_H_
#define SOCPUPPET_REGS_I2C_CONTROLLER_H_

/* How many bytes of address space the block takes. */
#define I2C_CONTROLLER_SIZE 0x1000U

/*
 * The low byte of the clock's prescale: the bus's clock is the controller's
 * divided by five times one more than the prescale.
 */
#define I2C_CONTROLLER_PRESCALE_LOW             0x000U
#define I2C_CONTROLLER_PRESCALE_LOW_AT_RESET    0x000000FFU
#define I2C_CONTROLLER_PRESCALE_LOW_VALUE_MASK  0x000000FFU
#define I2C_CONTROLLER_PRESCALE_LOW_VALUE_SHIFT 0U

/* The high byte of the clock's prescale. */
#define I2C_CONTROLLER_PRESCALE_HIGH             0x004U
#define I2C_CONTROLLER_PRESCALE_HIGH_AT_RESET    0x000000FFU
#define I2C_CONTROLLER_PRESCALE_HIGH_VALUE_MASK  0x000000FFU
#define I2C_CONTROLLER_PRESCALE_HIGH_VALUE_SHIFT 0U

/* Switches the controller on, and its interrupt. */
#define I2C_CONTROLLER_CONTROL                  0x008U
/* The interrupt is raised when a command is done. */
#define I2C_CONTROLLER_CONTROL_INTERRUPT_ENABLE (1U << 6)
/* The controller is on: commands are carried out. */
#define I2C_CONTROLLER_CONTROL_ENABLE           (1U << 7)

/*
 * The next byte to send: an address, with the direction in bit 0 (1 is a
 * read), or a byte of data.
 */
#define I2C_CONTROLLER_TRANSMIT             0x00CU
#define I2C_CONTROLLER_TRANSMIT_VALUE_MASK  0x000000FFU
#define I2C_CONTROLLER_TRANSMIT_VALUE_SHIFT 0U

/* The last byte received. */
#define I2C_CONTROLLER_RECEIVE             0x00CU
#define I2C_CONTROLLER_RECEIVE_VALUE_MASK  0x000000FFU
#define I2C_CONTROLLER_RECEIVE_VALUE_SHIFT 0U

/* What the controller is to do next. Reads as status. */
#define I2C_CONTROLLER_COMMAND                 0x010U
/* Clears the interrupt. */
#define I2C_CONTROLLER_COMMAND_CLEAR_INTERRUPT (1U << 0)
/* With a read: do not acknowledge the byte, which ends the read. */
#define I2C_CONTROLLER_COMMAND_NACK            (1U << 3)
/* Send the byte in `TRANSMIT`. */
#define I2C_CONTROLLER_COMMAND_WRITE           (1U << 4)
/* Receive a byte into `RECEIVE`. */
#define I2C_CONTROLLER_COMMAND_READ            (1U << 5)
/* After the byte, end the transfer. */
#define I2C_CONTROLLER_COMMAND_STOP            (1U << 6)
/* Before the byte, start a transfer, or start again. */
#define I2C_CONTROLLER_COMMAND_START           (1U << 7)

/* What the controller is doing, and what came of its last command. */
#define I2C_CONTROLLER_STATUS                      0x010U
/* A command is done, and the interrupt not cleared. */
#define I2C_CONTROLLER_STATUS_INTERRUPT            (1U << 0)
/* A command is being carried out. */
#define I2C_CONTROLLER_STATUS_TRANSFER_IN_PROGRESS (1U << 1)
/* Another controller won the bus. Never set: this one is alone on it. */
#define I2C_CONTROLLER_STATUS_ARBITRATION_LOST     (1U << 5)
/* Between a start and a stop. */
#define I2C_CONTROLLER_STATUS_BUSY                 (1U << 6)
/* The last byte sent was not acknowledged. */
#define I2C_CONTROLLER_STATUS_NO_ACK               (1U << 7)

#endif /* SOCPUPPET_REGS_I2C_CONTROLLER_H_ */
