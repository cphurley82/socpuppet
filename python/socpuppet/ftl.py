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
after a run, read back what the host wrote. Both of the SSD's firmwares
read the table this way when they start, and the SSD's contract tests hold
them and this module to each other (`tests/python/test_ssd_firmware.py`,
docs/models/ssd-firmware.md).
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
NOWHERE = 0xFFFF_FFFF
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


class Table(NamedTuple):
    """A table the reserve holds."""

    #: For each page of the drive, the NAND page that holds it, or NOWHERE.
    where: tuple[int, ...]
    #: The next NAND page nobody has.
    next_free: int


def saved_reserve(table: Table, *, page_size: int) -> bytes:
    """What a save writes to the reserve: the header page, then the table.

    Whole pages, each filled out with ones, as erased, for as many pages
    as `saved_pages` says.
    """
    drive_pages = len(table.where)
    saved = bytearray(
        _ERASED
        * (
            saved_pages(drive_pages=drive_pages, page_size=page_size)
            * page_size
        )
    )
    for offset, word in (
        (header.MAGIC, header.MAGIC_NUMBER),
        (header.VERSION, header.VERSION_FIRST),
        (header.PAGES, drive_pages),
        (header.NEXT_FREE, table.next_free),
    ):
        struct.pack_into("<I", saved, offset, word)
    struct.pack_into(f"<{drive_pages}{_ENTRY}", saved, page_size, *table.where)
    return bytes(saved)


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
    table = [NOWHERE] * pages
    for number in range(_whole(len(drive), page_size)):
        piece = drive[number * page_size : (number + 1) * page_size]
        if any(piece):
            table[number] = reserve + len(data) // page_size
            data += piece.ljust(page_size, b"\0")
    saved = saved_reserve(
        Table(tuple(table), reserve + len(data) // page_size),
        page_size=page_size,
    )
    return saved.ljust(reserve * page_size, _ERASED) + bytes(data)


def saved_pages(*, drive_pages: int, page_size: int) -> int:
    """How many of the reserve's pages a saved table takes, header and all."""
    return 1 + _whole(drive_pages * _ENTRY_SIZE, page_size)


def saved_table(
    reserve: bytes, *, layout: Layout, page_size: int
) -> Table | None:
    """The table that `reserve`, the reserve's first pages, holds.

    `reserve` is at least the `saved_pages` the header and the table take.
    None if its header is not one for a drive of `layout.drive_pages`, as
    on a NAND fresh from the factory, whose erased header says nothing; or
    if the table it holds cannot be this drive's: the pages given out so
    far are the reserve's end up to the next free one, which is at most
    the NAND's end, so an entry anywhere else is not one of this drive's.
    """
    said = tuple(
        struct.unpack_from("<I", reserve, offset)[0]
        for offset in (header.MAGIC, header.VERSION, header.PAGES)
    )
    if said != (header.MAGIC_NUMBER, header.VERSION_FIRST, layout.drive_pages):
        return None
    (next_free,) = struct.unpack_from("<I", reserve, header.NEXT_FREE)
    table = Table(
        struct.unpack_from(
            f"<{layout.drive_pages}{_ENTRY}", reserve, page_size
        ),
        next_free,
    )
    return table if _can_be_this_drives(table, layout) else None


def _can_be_this_drives(table: Table, layout: Layout) -> bool:
    """Whether every page `table` gives out is one the NAND has given."""
    given_out = range(layout.reserve_pages, table.next_free)
    return table.next_free <= layout.reserve_pages + layout.drive_pages and all(
        where == NOWHERE or where in given_out for where in table.where
    )


def drive_image(nand: bytes, chip: IdealNand) -> bytes:
    """The drive that `nand`, every page of `chip`, holds, by its table.

    A page of the drive that no NAND page holds reads as zeros. A NAND
    whose reserve holds no table that can be this drive's (`saved_table`),
    such as one never programmed, holds a drive of zeros, as the firmware
    finds it.
    """
    page_size = chip.page_size
    shared = _layout_of(chip)
    table = saved_table(nand, layout=shared, page_size=page_size)
    if table is None:
        return bytes(shared.drive_pages * page_size)
    return b"".join(
        bytes(page_size)
        if where == NOWHERE
        else nand[where * page_size : (where + 1) * page_size]
        for where in table.where
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
