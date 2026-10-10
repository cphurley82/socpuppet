"""Milestone M6's exit test: the host's firmware with the SSD's firmware.

It is M3b's exit test with the drive swapped. The host's firmware is the
same image, Zephyr's own test of its disk interface, built for the board
`socpuppet_host` with the shield `socpuppet_host_drive`. Where M3b's host
had 🎭 the stand-in drive on its PCIe link, this one has the SSD of
`socpuppet.boards.ssd`, which is hardware that does nothing until
firmware tells it to.

Nothing was built again for this. The host cannot tell which drive it
has, so its image is M3b's.
"""

import functools

import pytest

import socpuppet as sp
from disk_access import IMAGE, run_to_a_verdict
from socpuppet.boards.host import host
from socpuppet.boards.ssd import add_ssd, stand_in_firmware
from ssd_zephyr_firmware import BANNER
from ssd_zephyr_firmware import IMAGE as SSD_IMAGE

#: What is in the SSD's CPU's place.
A_SCRIPT = "a script for the SSD's firmware"
ZEPHYR = "Zephyr for the SSD's firmware"


@pytest.fixture(params=[A_SCRIPT, ZEPHYR])
def host_with_the_ssd(request, firmware):
    """Builds the host with the SSD, with every image loaded.

    The host's image is Zephyr's disk test. Every test that asks for this
    runs twice: once with 🎭 the Python stand-in for the SSD's firmware,
    in its CPU's place, and once with the real thing, the Zephyr
    application in firmware/ssd on the SSD's own CPU. A test of what only
    the real thing does asks for that one alone, with `only_with_zephyr`.
    """
    host_image = firmware(IMAGE)
    ssd_image = firmware(SSD_IMAGE) if request.param == ZEPHYR else None

    def build(blocks):
        board = host(
            drive_blocks=blocks,
            drive=add_ssd
            if ssd_image
            else functools.partial(
                add_ssd, firmware=stand_in_firmware().script
            ),
        )
        board.platform.build()
        # With two bus masters, the platform has to be told whose
        # firmware an image is.
        board.platform.load_elf(host_image, via=board.cpu.socket)
        if ssd_image:
            board.platform.load_elf(ssd_image, via=board.drive.ssd.cpu.socket)
        return board

    return build


only_with_zephyr = pytest.mark.parametrize(
    "host_with_the_ssd", [ZEPHYR], indirect=True
)


@pytest.mark.platform
class TestWhenZephyrsDiskTestRunsOnTheHostWithTheSsd:
    def test_its_read_and_write_tests_pass(self, host_with_the_ssd):
        # 2 MiB, as in M3b.
        board = host_with_the_ssd(blocks=4096)

        run_to_a_verdict(board)

        assert "PASS - [disk_driver.test_read]" in board.uart.output
        assert "PASS - [disk_driver.test_write]" in board.uart.output

    @only_with_zephyr
    def test_each_firmware_prints_on_its_own_console(self, host_with_the_ssd):
        board = host_with_the_ssd(blocks=4096)
        ssds_console = board.drive.ssd.cpu_kit.uart

        run_to_a_verdict(board)

        assert BANNER in ssds_console.output
        assert BANNER not in board.uart.output
        assert "disk_driver" in board.uart.output
        assert "disk_driver" not in ssds_console.output


#: The largest drive the SSD's firmware takes: 2 GiB, in 512-byte blocks.
LARGEST_DRIVE = 2 * (1 << 30) // 512


@pytest.mark.platform
@only_with_zephyr
class TestWhenTheSsdsFirmwareTakesAQuarterOfASecondToComeReady:
    """A host that is ready first has to wait for its drive.

    Both CPUs leave reset together. The SSD's firmware starts by making an
    empty table of the drive's pages, which takes it half a microsecond a
    page: 0.27 s for the largest drive it takes. Zephyr on the host gets
    to the drive and enables it 0.12 s in. The SSD's hardware remembers
    that it was enabled until the firmware gets to it, and the host is
    kept waiting for 0.15 s.

    Zephyr's driver waits for a drive to say it is ready for as long as
    the drive's own registers tell it to and half a second more, which
    for this SSD is a second and a half.
    """

    def test_the_host_finds_the_drive_and_its_tests_pass(
        self, host_with_the_ssd
    ):
        board = host_with_the_ssd(blocks=LARGEST_DRIVE)

        run_to_a_verdict(board)

        assert f"Disk reports {LARGEST_DRIVE} sectors" in board.uart.output
        assert "PASS - [disk_driver.test_read]" in board.uart.output
        assert "PASS - [disk_driver.test_write]" in board.uart.output


#: Long enough for a host whose SSD is ready at once to have printed its
#: banner, which it does at 0.14 s, and too short for the SSD to have made
#: the table of its largest drive. The two tests below hold it to both.
A_FIFTH_OF_A_SECOND = sp.ms(200)


@pytest.mark.platform
@only_with_zephyr
class TestAFifthOfASecondAfterBothCpusStart:
    """What shows that the host of the slow SSD above really is waiting.

    Zephyr starts its drivers before it prints its banner, so a host that
    is waiting for its drive has printed nothing.
    """

    def test_a_host_whose_ssd_was_ready_at_once_has_printed_its_banner(
        self, host_with_the_ssd
    ):
        board = host_with_the_ssd(blocks=4096)

        board.platform.run(A_FIFTH_OF_A_SECOND)

        assert "Booting Zephyr" in board.uart.output

    def test_a_host_whose_ssd_is_making_its_table_has_printed_nothing(
        self, host_with_the_ssd
    ):
        board = host_with_the_ssd(blocks=LARGEST_DRIVE)

        board.platform.run(A_FIFTH_OF_A_SECOND)

        assert board.uart.output == ""
