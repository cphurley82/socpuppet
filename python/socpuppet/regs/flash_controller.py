"""Flash controller: the registers.

Moves a page between the NAND flash chip and the SSD's own memory, or erases a
block, one command at a time.

Generated from regs/flash_controller.rdl by tools/regs.py. Do not edit: change
the register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x30

#: Write a command to have it carried out on what the other registers say.
#: Reads as zero.
COMMAND = 0x00
#: Read a page of the chip into the SSD's own memory.
COMMAND_READ_PAGE = 1
#: Program a page of the chip from the SSD's own memory.
COMMAND_PROGRAM_PAGE = 2
#: Erase a block of the chip.
COMMAND_ERASE_BLOCK = 3
#: Ask the chip what it is. `PAGE_SIZE`, `PAGES_PER_BLOCK` and `BLOCKS` read
#: as zero until this has been done.
COMMAND_IDENTIFY = 4

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

#: Which block of the chip.
BLOCK = 0x0C

#: Which page of that block.
PAGE = 0x10

#: Where the page is, or goes, in the SSD's own memory.
LOCAL_ADDRESS = 0x14

#: How big a page of the chip is, in bytes.
PAGE_SIZE = 0x20

#: How many pages make a block.
PAGES_PER_BLOCK = 0x24

#: How many blocks the chip has.
BLOCKS = 0x28
