"""The SSD's flash translation layer as it lies on the NAND.

🎓 The flash translation layer (FTL) is the part of an SSD's firmware that
says which page of NAND flash holds each page of the drive. A host writes
the drive's pages in whatever order it likes, and the FTL gives each one
the next NAND page nobody has, and notes it in a table. The table lives in
the firmware's RAM while the drive runs, and on the NAND while it is off.

Where on the NAND: a reserve, the chip's first blocks, which the drive's
pages never go in. Its first page is a header, `socpuppet.regs.ftl_header`,
which says whose table follows; from its second page, the table: for each
page of the drive, which NAND page holds it, a little-endian 32-bit word,
all ones for none. An erased page reads as all ones, so a chip fresh from
the factory has no header, and holds a drive of zeros.

This module is that layout in Python, so that Python can do what a factory
does: program a drive's NAND with a filesystem before the first boot. And,
after a run, read back what the host wrote. 🚧 The firmware's own copy of
the layout, which reads the table when it starts and saves it when the host
shuts the drive down, comes with M24, and the SSD's contract tests then hold
the two to each other (docs/models/ssd-firmware.md).
"""

from __future__ import annotations

import struct
from typing import NamedTuple

from socpuppet.components import IdealNand
from socpuppet.regs import ftl_header as header

#: An entry of the table: the NAND page that holds a page of the drive.
_ENTRY = "I"
_ENTRY_SIZE = struct.calcsize(_ENTRY)
#: The entry of a page of the drive that no NAND page holds.
_NOWHERE = 0xFFFF_FFFF
#: What an erased NAND cell holds.
_ERASED = b"\xff"


def reserved_blocks(
    chip_blocks: int, *, pages_per_block: int, page_size: int
) -> int:
    """How many of a NAND's blocks, at its start, the FTL keeps for itself.

    The fewest whole blocks that hold a header page and an entry for each
    of the chip's pages: an entry for each page of the drive, and some to
    spare, so that the reserve can be worked out from the chip alone.
    """
    needed = page_size + _ENTRY_SIZE * pages_per_block * chip_blocks
    return _whole(needed, pages_per_block * page_size)


class Layout(NamedTuple):
    """How a NAND's pages are shared between the FTL and the drive."""

    #: How many pages, at the NAND's start, are the reserve. The drive's
    #: pages start at this NAND page.
    reserve_pages: int
    #: How many pages the drive has: the NAND's others.
    drive_pages: int


def layout(blocks: int, *, pages_per_block: int, page_size: int) -> Layout:
    """How a NAND of `blocks` blocks is shared between the FTL and the drive."""
    reserve = pages_per_block * reserved_blocks(
        blocks, pages_per_block=pages_per_block, page_size=page_size
    )
    return Layout(reserve, blocks * pages_per_block - reserve)


def nand_blocks(
    data_blocks: int, *, pages_per_block: int, page_size: int
) -> int:
    """The fewest NAND blocks that hold `data_blocks` besides the reserve.

    `data_blocks` is how many of the NAND's blocks the drive's pages fill:
    the drive's size in NAND blocks, not in the drive's own blocks.
    """
    blocks = data_blocks + 1
    while (
        blocks
        - reserved_blocks(
            blocks, pages_per_block=pages_per_block, page_size=page_size
        )
        < data_blocks
    ):
        blocks += 1
    return blocks


def nand_image(drive: bytes, chip: IdealNand) -> bytes:
    """`chip` programmed with `drive`, as a factory would, for `nand.load`.

    Each page of the drive that is not all zeros takes the next NAND page
    after the reserve, in order, as if a host had written the drive's
    pages in order to a drive fresh from the factory. A page of zeros
    takes none: it reads as zeros, as a page never written does. The image
    ends with the last page it programs, so that the rest of the chip stays
    erased. Raises ValueError if `drive` is bigger than the drive the chip
    holds.
    """
    page_size = chip.page_size
    reserve, pages = _layout_of(chip)
    if len(drive) > pages * page_size:
        raise ValueError(
            f"The drive's image is {len(drive)} bytes, and the drive the "
            f"NAND holds besides the FTL's reserve holds {pages * page_size}. "
            "Describe a bigger drive."
        )
    data = bytearray()
    table = [_NOWHERE] * pages
    for number in range(_whole(len(drive), page_size)):
        piece = drive[number * page_size : (number + 1) * page_size]
        if any(piece):
            table[number] = reserve + len(data) // page_size
            data += piece.ljust(page_size, b"\0")
    image = bytearray(_ERASED * (reserve * page_size))
    for offset, word in (
        (header.MAGIC, header.MAGIC_NUMBER),
        (header.VERSION, header.VERSION_FIRST),
        (header.PAGES, pages),
        (header.NEXT_FREE, reserve + len(data) // page_size),
    ):
        struct.pack_into("<I", image, offset, word)
    struct.pack_into(f"<{pages}{_ENTRY}", image, page_size, *table)
    return bytes(image + data)


def drive_image(nand: bytes, chip: IdealNand) -> bytes:
    """The drive that `nand`, every page of `chip`, holds, by its table.

    A page of the drive that no NAND page holds reads as zeros. A NAND
    whose header is not one for this drive, such as one never programmed,
    holds a drive of zeros, as the firmware finds it.
    """
    page_size = chip.page_size
    _, pages = _layout_of(chip)
    said = tuple(
        struct.unpack_from("<I", nand, offset)[0]
        for offset in (header.MAGIC, header.VERSION, header.PAGES)
    )
    if said != (header.MAGIC_NUMBER, header.VERSION_FIRST, pages):
        return bytes(pages * page_size)
    table = struct.unpack_from(f"<{pages}{_ENTRY}", nand, page_size)
    return b"".join(
        bytes(page_size)
        if where == _NOWHERE
        else nand[where * page_size : (where + 1) * page_size]
        for where in table
    )


def _layout_of(chip: IdealNand) -> Layout:
    """How `chip` is shared between the FTL and the drive."""
    return layout(
        chip.blocks,
        pages_per_block=chip.pages_per_block,
        page_size=chip.page_size,
    )


def _whole(amount: int, size: int) -> int:
    """How many pieces of `size` hold `amount`: the division, rounded up."""
    return -(-amount // size)
