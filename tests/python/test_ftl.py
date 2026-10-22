"""The SSD's flash translation layer as it lies on the NAND, in Python.

🎓 The flash translation layer (FTL) is the part of the SSD's firmware
that says which NAND page holds each page of the drive. It keeps that
table in its RAM, and on the NAND when the drive is switched off, in a
reserve at the NAND's start. `socpuppet.ftl` reads and writes that
layout, so that Python can program a drive's NAND with a filesystem
before a boot, as a factory does, and read back what a host wrote to it
after.
"""

import struct

import pytest

import socpuppet as sp
from socpuppet import ftl

#: A small chip for the tests: 4 blocks of 4 pages of 64 bytes. Its first
#: block is the reserve, so the drive is the other 12 pages.
CHIP = sp.IdealNand(blocks=4, pages_per_block=4, page_size=64)
PAGE = 64
CHIP_BYTES = 4 * 4 * PAGE
DRIVE_PAGES = 12
#: The first NAND page after the reserve, where the drive's pages start.
AFTER_THE_RESERVE = 4
#: The SSD's own chip: 4 KiB pages, 64 to a block.
SSD_PAGE = 4096
SSD_PAGES_PER_BLOCK = 64


def page(text):
    """A page of the drive holding `text`, then zeros."""
    return text.ljust(PAGE, b"\0")


def nand_page(nand, number):
    """NAND page `number` of a NAND's image."""
    return nand[number * PAGE : (number + 1) * PAGE]


def loaded(image):
    """The whole chip, programmed with `image`: what `nand.load` leaves."""
    return image.ljust(CHIP_BYTES, b"\xff")


class TestTheReserve:
    @pytest.mark.parametrize(
        ("chip_blocks", "reserved"),
        [(1, 1), (1008, 1), (1009, 2), (8192, 9)],
    )
    def test_is_the_fewest_blocks_for_a_header_page_and_an_entry_a_page(
        self, chip_blocks, reserved
    ):
        # 🎓 A page of 4 KiB holds the entries of 1024 pages, 16 blocks of
        # 64: one block of the reserve holds the header and 63 pages of
        # entries, enough for a NAND of 1008 blocks.
        assert (
            ftl.reserved_blocks(
                chip_blocks,
                pages_per_block=SSD_PAGES_PER_BLOCK,
                page_size=SSD_PAGE,
            )
            == reserved
        )


class TestTheNandForADrive:
    @pytest.mark.parametrize(
        ("data_blocks", "nand_blocks"),
        [(1, 2), (1007, 1008), (1008, 1010), (1009, 1011), (8183, 8192)],
    )
    def test_is_the_fewest_blocks_that_hold_the_drive_besides_its_reserve(
        self, data_blocks, nand_blocks
    ):
        # 🎓 A NAND of 1009 blocks needs a reserve of 2, so it holds a drive
        # of 1007 blocks, as one of 1008 does: a drive of 1008 needs 1010.
        assert (
            ftl.nand_blocks(
                data_blocks,
                pages_per_block=SSD_PAGES_PER_BLOCK,
                page_size=SSD_PAGE,
            )
            == nand_blocks
        )


class TestWhenADriveImageIsMadeANandImage:
    def test_reading_the_nand_back_gives_the_drive_with_zeros_after_it(self):
        drive = page(b"spam") + page(b"eggs") + b"ham"

        nand = ftl.nand_image(drive, CHIP)

        assert ftl.drive_image(loaded(nand), CHIP) == drive.ljust(
            DRIVE_PAGES * PAGE, b"\0"
        )

    def test_its_pages_go_after_the_reserve_in_order_and_zero_ones_nowhere(
        self,
    ):
        # 🎓 As if a host had written the drive's pages in order to a
        # drive fresh from the factory: each takes the next NAND page, and
        # a page of zeros is one the host never wrote, which reads as
        # zeros without a NAND page.
        drive = page(b"spam") + page(b"") + page(b"eggs")

        nand = ftl.nand_image(drive, CHIP)

        assert nand_page(nand, AFTER_THE_RESERVE) == page(b"spam")
        assert nand_page(nand, AFTER_THE_RESERVE + 1) == page(b"eggs")

    def test_it_ends_with_the_last_page_it_programs(self):
        # So that the chip's other pages stay erased, and take no memory.
        drive = page(b"spam") + page(b"") + page(b"eggs")

        nand = ftl.nand_image(drive, CHIP)

        assert len(nand) == (AFTER_THE_RESERVE + 2) * PAGE

    def test_the_reserves_first_page_says_whose_table_follows_and_where_next(
        self,
    ):
        # The header: "SFTL", the layout's version, how many pages the
        # drive has, and the next NAND page nobody has. Then the table, an
        # entry of 4 bytes for each page of the drive, which NAND page holds
        # it, all ones for none.
        drive = page(b"spam") + page(b"") + page(b"eggs")

        nand = ftl.nand_image(drive, CHIP)

        header = struct.unpack_from("<4sIII", nand, 0)
        table = struct.unpack_from(f"<{DRIVE_PAGES}I", nand, PAGE)
        assert header == (b"SFTL", 1, DRIVE_PAGES, AFTER_THE_RESERVE + 2)
        assert table[:4] == (
            AFTER_THE_RESERVE,
            0xFFFF_FFFF,
            AFTER_THE_RESERVE + 1,
            0xFFFF_FFFF,
        )

    def test_a_drive_image_bigger_than_the_drive_is_refused(self):
        with pytest.raises(ValueError, match=r"769 bytes.*holds 768"):
            ftl.nand_image(bytes(DRIVE_PAGES * PAGE + 1), CHIP)


class TestWhenANandWasNeverProgrammed:
    def test_the_drive_reads_as_zeros(self):
        erased = b"\xff" * CHIP_BYTES

        assert ftl.drive_image(erased, CHIP) == bytes(DRIVE_PAGES * PAGE)
