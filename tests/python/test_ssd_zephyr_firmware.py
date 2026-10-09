"""What the SSD's Zephyr firmware says for itself, on its console.

What a host sees of the firmware is in test_ssd_firmware.py, where the
Zephyr application in firmware/ssd and 🎭 its Python stand-in are held to
the same tests. A console is something only the real one has.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd

# The drive's blocks are 512 bytes, and there are this many in a GiB.
BLOCKS_PER_GIB = (1 << 30) // 512


def console_of_an_ssd(firmware, *, blocks, until):
    """Boots the firmware on an SSD of `blocks` blocks, with an idle host.

    Runs until `until` is on the console, and returns all that is there.
    """
    board = ssd(host=idle_host, blocks=blocks)
    board.platform.build()
    board.platform.load_elf(
        firmware("ssd_socpuppet_ssd.elf"), via=board.ssd.cpu.socket
    )
    console = board.ssd.cpu_kit.uart
    # The firmware starts by making an empty table of the drive's pages,
    # which takes it about half a microsecond of simulated time a page:
    # a quarter of a second for 2 GiB. A second leaves room and still ends
    # a run that never prints.
    board.platform.run_until(
        lambda: until in console.output, timeout=sp.ms(1000)
    )
    return console.output


@pytest.mark.platform
class TestWhenTheSsdsFirmwareStarts:
    def test_it_says_what_drive_it_found(self, firmware):
        # 512 blocks of 512 bytes are 64 NAND pages of 4 KiB.
        banner = "socpuppet SSD firmware: a drive of 64 pages of 4096 bytes\r\n"

        assert banner in console_of_an_ssd(firmware, blocks=512, until=banner)


@pytest.mark.platform
class TestWhenTheNandIsBiggerThanZephyrsFlashApiCanReach:
    """Zephyr names a place on a flash with an `off_t`.

    On a 32-bit CPU that is 32 bits and signed, so the last place it can
    name is just short of 2 GiB (docs/upstream.md).
    """

    def test_the_firmware_says_so_and_stops(self, firmware):
        said = console_of_an_ssd(
            firmware, blocks=3 * BLOCKS_PER_GIB, until="stops"
        )

        assert (
            "The NAND is 3072 MiB, and Zephyr's flash API reaches only "
            "the first 2048 MiB of one on this CPU." in said
        )
        assert "a drive of" not in said

    def test_a_nand_of_exactly_what_it_can_reach_is_a_drive(self, firmware):
        banner = "a drive of 524288 pages of 4096 bytes\r\n"

        said = console_of_an_ssd(
            firmware, blocks=2 * BLOCKS_PER_GIB, until=banner
        )

        assert banner in said
