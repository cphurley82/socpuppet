"""Boot image header: the registers.

What a boot image starts with: what the program after it is, where it goes,
and a sum to check it by.

Generated from regs/boot_image_header.rdl by tools/regs.py. Do not edit:
change the register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x40

#: What says this is an image at all.
MAGIC = 0x00
#: The four bytes `SOCP`, which as a little-endian number is 0x50434F53.
MAGIC_NUMBER = 1346588499

#: Which kind of CPU the program was built for, by the width of its registers
#: in bits.
XLEN = 0x04
#: A program for a 32-bit CPU.
XLEN_RV32 = 32
#: A program for a 64-bit CPU.
XLEN_RV64 = 64

#: Where in memory the program's first byte goes, the low 32 bits.
LOAD_ADDRESS_LOW = 0x08

#: The high 32 bits, which are zero for a 32-bit CPU.
LOAD_ADDRESS_HIGH = 0x0C

#: Where the CPU starts executing once the program is in memory, the low 32
#: bits.
ENTRY_LOW = 0x10

#: The high 32 bits.
ENTRY_HIGH = 0x14

#: How many bytes the program is: what follows the header.
LENGTH = 0x18

#: The CRC-32 of the program's bytes, as zlib and Ethernet compute it. The
#: header is not in it.
CRC = 0x1C

#: The image's name, as text, for a boot ROM to say which image it could not
#: start. Up to 32 bytes of UTF-8, with zeros after a shorter one. A name of
#: all 32 bytes has no zero after it.
NAME = 0x20
NAME_SIZE = 0x20
