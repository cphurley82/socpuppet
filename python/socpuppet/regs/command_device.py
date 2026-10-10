"""Command device: the registers.

The three registers of any device its CPU gives one command at a time.

Generated from regs/command_device.rdl by tools/regs.py. Do not edit: change
the register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x0C

#: Write a command to have it carried out. Reads as zero.
COMMAND = 0x00

#: How the last command went. Giving the next command forgets it.
STATUS = 0x04
#: The command was carried out.
STATUS_DONE = 1 << 0
#: The command was not carried out, or not all of it.
STATUS_ERROR = 1 << 1
#: A command has been given and is not yet carried out. No other is taken
#: meanwhile.
STATUS_BUSY = 1 << 2

#: Which bits of `STATUS` raise the interrupt line while they are set.
INTERRUPT_ENABLE = 0x08
INTERRUPT_ENABLE_DONE = 1 << 0
INTERRUPT_ENABLE_ERROR = 1 << 1
