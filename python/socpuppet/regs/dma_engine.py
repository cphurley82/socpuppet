"""DMA engine: the registers.

Copies between the host's memory and the SSD's own, one copy for each command.

Generated from regs/dma_engine.rdl by tools/regs.py. Do not edit: change the
register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x20

#: Write a command to start a copy of what the other registers say. Reads as
#: zero.
COMMAND = 0x00
#: Copy from the host's memory into the SSD's own.
COMMAND_FROM_HOST = 1
#: Copy from the SSD's own memory to the host's.
COMMAND_TO_HOST = 2

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

#: Where in the host's memory, the low 32 bits.
HOST_ADDRESS_LOW = 0x0C

#: The high 32 bits. A host's memory can be above 4 GiB even when the SSD's
#: CPU is a 32-bit one.
HOST_ADDRESS_HIGH = 0x10

#: Where in the SSD's own memory.
LOCAL_ADDRESS = 0x14

#: How many bytes.
LENGTH = 0x18
