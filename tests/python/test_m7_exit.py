"""Milestone M7's exit test: the host across the real die-to-die link.

The host of M3 and M6 was two dies with 🎭 a stand-in between them, a
link that passes every access straight through. Here the link is the
real one (`sp.D2dLink`), which carries no traffic until it has been
trained, and the IO die has 🎭 the script for a manager to train it. The
link's end on the compute die holds the host's CPU in reset until the
manager lets it go.

Nothing was built again for this. The host's firmware cannot tell which
link it has, so its images are M3's: Zephyr's `hello_world` and its test
of its disk interface.
"""

import functools

import pytest

import socpuppet as sp
from disk_access import IMAGE, run_to_a_verdict
from socpuppet.boards.host import host
from socpuppet.boards.manager import add_manager, stand_in_manager
from socpuppet.boards.ssd import add_ssd, stand_in_firmware

GREETING = "Hello World! socpuppet_host"


def a_scripted_manager():
    """🎭 The script for a manager, as `host(manager=)` takes it."""
    return functools.partial(add_manager, script=stand_in_manager().script)


@pytest.mark.platform
class TestWhenZephyrsHelloWorldBootsOnTheHostAcrossTheRealLink:
    def test_it_prints_its_greeting_with_the_boards_name(self, firmware):
        board = host(manager=a_scripted_manager())
        board.platform.build()
        # With two bus masters, the platform has to be told whose
        # firmware an image is.
        board.platform.load_elf(
            firmware("hello_world_socpuppet_host.elf"), via=board.cpu.socket
        )

        # The link takes 5 ms to come up and the greeting a millisecond
        # more. 50 ms leaves room and still ends a run that never prints.
        board.platform.run_until(
            lambda: GREETING in board.uart.output, timeout=sp.ms(50)
        )

        assert GREETING in board.uart.output


#: How long UCIe holds a link in reset after power-on.
THE_RESET_HOLD = sp.ms(4)


@pytest.mark.platform
class TestFourMillisecondsAfterPowerOn:
    """What shows that the host across the real link starts late.

    Four milliseconds is UCIe's reset hold, so no manager can have the
    link up yet. Zephyr's `hello_world` has said all it has to say a
    millisecond after its CPU starts.
    """

    def test_a_host_with_the_stand_in_link_has_printed_its_greeting(
        self, firmware
    ):
        board = host()
        board.platform.build()
        board.platform.load_elf(firmware("hello_world_socpuppet_host.elf"))

        board.platform.run(THE_RESET_HOLD)

        assert GREETING in board.uart.output

    def test_a_host_across_the_real_link_has_printed_nothing(self, firmware):
        board = host(manager=a_scripted_manager())
        board.platform.build()
        board.platform.load_elf(
            firmware("hello_world_socpuppet_host.elf"), via=board.cpu.socket
        )

        board.platform.run(THE_RESET_HOLD)

        assert board.uart.output == ""


#: What is on the host's PCIe link.
THE_STAND_IN_DRIVE = "the stand-in drive"
THE_SSD_WITH_A_SCRIPT = "the SSD, with a script for its firmware"
THE_SSD_WITH_ZEPHYR = "the SSD, with Zephyr for its firmware"


@pytest.fixture(
    params=[THE_STAND_IN_DRIVE, THE_SSD_WITH_A_SCRIPT, THE_SSD_WITH_ZEPHYR]
)
def host_across_the_link(request, firmware):
    """The host across the real link, with a drive and every image loaded.

    The host's image is Zephyr's disk test. A test that asks for this runs
    three times, once for each thing M3b and M6 put on the host's PCIe
    link: 🎭 the stand-in drive, the SSD with 🎭 a script for its firmware,
    and the SSD with the Zephyr application of firmware/ssd on a CPU of
    its own.
    """
    drives = {
        THE_STAND_IN_DRIVE: {},
        THE_SSD_WITH_A_SCRIPT: {
            "drive": functools.partial(
                add_ssd, firmware=stand_in_firmware().script
            )
        },
        THE_SSD_WITH_ZEPHYR: {"drive": add_ssd},
    }
    # 2 MiB, as in M3b and M6.
    board = host(
        drive_blocks=4096,
        manager=a_scripted_manager(),
        **drives[request.param],
    )
    board.platform.build()
    board.platform.load_elf(firmware(IMAGE), via=board.cpu.socket)
    if request.param == THE_SSD_WITH_ZEPHYR:
        board.platform.load_elf(
            firmware("ssd_socpuppet_ssd.elf"), via=board.drive.ssd.cpu.socket
        )
    return board


@pytest.mark.platform
class TestWhenZephyrsDiskTestRunsOnTheHostAcrossTheRealLink:
    def test_its_read_and_write_tests_pass(self, host_across_the_link):
        board = host_across_the_link

        run_to_a_verdict(board)

        assert "PASS - [disk_driver.test_read]" in board.uart.output
        assert "PASS - [disk_driver.test_write]" in board.uart.output
