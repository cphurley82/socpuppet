"""Images of the SSD's NAND whose saved table cannot be this drive's.

The reserve's header is this drive's, so a firmware that took the table's
word would act on it: `socpuppet.ftl` and both firmwares are held to
refusing it (`test_ftl.py`, `test_ssd_firmware.py`), and Zephyr's to
saying so (`test_ssd_zephyr_firmware.py`).
"""

from socpuppet import ftl


def a_nand_whose_table_cannot_be_its(chip, where_page_0, next_free):
    """`chip`'s image with this drive's header and a table that is not its.

    A page of data is in the first NAND page after the reserve. The table
    says the drive's first page is in NAND page `where_page_0` and the next
    free page is `next_free`, each a function of the chip's layout.
    """
    shared = ftl.layout(
        chip.blocks,
        pages_per_block=chip.pages_per_block,
        page_size=chip.page_size,
    )
    where = (where_page_0(shared),) + (ftl.NOWHERE,) * (shared.drive_pages - 1)
    reserve = ftl.saved_reserve(
        ftl.Table(where, next_free(shared)), page_size=chip.page_size
    )
    return reserve.ljust(shared.reserve_pages * chip.page_size, b"\xff") + (
        some_data(chip.page_size // 512)
    )


def some_data(blocks):
    """Bytes for `blocks` blocks: no two neighbours the same."""
    return bytes(
        (index * 7 + index // 512) % 251 for index in range(blocks * 512)
    )
