"""I2C controller: the registers.

A controller on an I2C bus: it starts and stops transfers, and sends and
receives one byte at a time.

Generated from regs/i2c_controller.rdl by tools/regs.py. Do not edit: change
the register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x1000

#: The low byte of the clock's prescale: the bus's clock is the controller's
#: divided by five times one more than the prescale.
PRESCALE_LOW = 0x000
PRESCALE_LOW_AT_RESET = 0x000000FF
PRESCALE_LOW_VALUE_MASK = 0x000000FF
PRESCALE_LOW_VALUE_SHIFT = 0

#: The high byte of the clock's prescale.
PRESCALE_HIGH = 0x004
PRESCALE_HIGH_AT_RESET = 0x000000FF
PRESCALE_HIGH_VALUE_MASK = 0x000000FF
PRESCALE_HIGH_VALUE_SHIFT = 0

#: Switches the controller on, and its interrupt.
CONTROL = 0x008
#: The interrupt is raised when a command is done.
CONTROL_INTERRUPT_ENABLE = 1 << 6
#: The controller is on: commands are carried out.
CONTROL_ENABLE = 1 << 7

#: The next byte to send: an address, with the direction in bit 0 (1 is a
#: read), or a byte of data.
TRANSMIT = 0x00C
TRANSMIT_VALUE_MASK = 0x000000FF
TRANSMIT_VALUE_SHIFT = 0

#: The last byte received.
RECEIVE = 0x00C
RECEIVE_VALUE_MASK = 0x000000FF
RECEIVE_VALUE_SHIFT = 0

#: What the controller is to do next. Reads as status.
COMMAND = 0x010
#: Clears the interrupt.
COMMAND_CLEAR_INTERRUPT = 1 << 0
#: With a read: do not acknowledge the byte, which ends the read.
COMMAND_NACK = 1 << 3
#: Send the byte in `TRANSMIT`.
COMMAND_WRITE = 1 << 4
#: Receive a byte into `RECEIVE`.
COMMAND_READ = 1 << 5
#: After the byte, end the transfer.
COMMAND_STOP = 1 << 6
#: Before the byte, start a transfer, or start again.
COMMAND_START = 1 << 7

#: What the controller is doing, and what came of its last command.
STATUS = 0x010
#: A command is done, and the interrupt not cleared.
STATUS_INTERRUPT = 1 << 0
#: A command is being carried out.
STATUS_TRANSFER_IN_PROGRESS = 1 << 1
#: Another controller won the bus. Never set: this one is alone on it.
STATUS_ARBITRATION_LOST = 1 << 5
#: Between a start and a stop.
STATUS_BUSY = 1 << 6
#: The last byte sent was not acknowledged.
STATUS_NO_ACK = 1 << 7
