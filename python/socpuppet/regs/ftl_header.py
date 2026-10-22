"""FTL header: the registers.

The first page of the reserve: whose table follows it, and where the next page
the drive is written to goes.

Generated from regs/ftl_header.rdl by tools/regs.py. Do not edit: change the
register map and run `uv run python tools/lint.py --fix`.
"""

#: How many bytes of address space the block takes.
SIZE = 0x10

#: What says this is the FTL's header at all. A NAND never programmed reads
#: all ones here, and holds a drive of zeros.
MAGIC = 0x00
#: The four bytes `SFTL`, which as a little-endian number is 0x4C544653.
MAGIC_NUMBER = 1280591443

#: Which layout the table that follows is in.
VERSION = 0x04
#: The header, then the table from the reserve's second page: for each page of
#: the drive, the NAND page that holds it, a 32-bit word, all ones for none.
VERSION_FIRST = 1

#: How many pages the drive has, and so how many entries the table: a table
#: for a drive of another size is not this one's.
PAGES = 0x08

#: The next NAND page nobody has: where the next page of the drive that no
#: NAND page holds yet is written.
NEXT_FREE = 0x0C
