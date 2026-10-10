"""Milestone M8's exit test: the full bootchain, three firmwares.

M7's host crossed the real die-to-die link with 🎭 a script for the
manager that brings the link up. Here the manager is the real thing: a
32-bit CPU on the IO die running the Zephyr application of
`firmware/iomgr`, which trains the link and then lets the host's CPU out
of reset.

Then all three firmwares boot together: the manager's, the host's, which
is Zephyr's test of its disk interface, and the SSD's, which is the drive
that test reads and writes. Each has a console, and the three are heard
as one story.

No image is built for this. The manager's is the one M5 runs on the IO
manager board, the SSD's is the one M4 runs on the SSD board, and the
host's are the ones M3's tests run.
"""

import pytest

import socpuppet as sp
from disk_access import IMAGE as DISK_TEST
from disk_access import LIMIT, VERDICTS, no_verdict
from link_trace import (
    sent_to_the_compute_die,
    sent_to_the_io_die,
    when_the_host_was_let_go,
)
from manager_firmware import IMAGE as MANAGER_IMAGE
from manager_firmware import (
    LINK_UP,
    RELEASED,
    TRAINING,
    console_of,
    what_the_manager_said,
)
from socpuppet.boards.host import host
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import add_ssd
from ssd_zephyr_firmware import BANNER as SSD_BANNER
from ssd_zephyr_firmware import IMAGE as SSD_IMAGE

GREETING = "Hello World! socpuppet_host"
#: Zephyr takes a millisecond or two to start on the manager, the link
#: five more to come up, and the host's greeting a millisecond after
#: that. This leaves room and still ends a run that never prints.
LONG_ENOUGH = sp.ms(50)


@pytest.mark.platform
class TestWhenTheManagersFirmwareBootsUnderAHostWithZephyrsHelloWorld:
    def test_the_host_prints_its_greeting(self, firmware):
        board = host_with_a_manager_running(firmware)

        board.platform.run_until(
            lambda: GREETING in board.uart.output, timeout=LONG_ENOUGH
        )

        assert GREETING in board.uart.output

    def test_the_managers_console_reads_training_then_link_up_then_released(
        self, firmware
    ):
        board = host_with_a_manager_running(firmware)
        console = console_of(board)

        board.platform.run_until(
            lambda: RELEASED in console.output, timeout=LONG_ENOUGH
        )

        assert what_the_manager_said(console) == [TRAINING, LINK_UP, RELEASED]


@pytest.mark.platform
class TestWhenTheManagerUnderAHostRunsFirmwareThatLeavesTheLinkAlone:
    def test_the_host_prints_nothing(self, firmware):
        # Zephyr's `hello_world` for the manager's board greets and stops.
        board = host_with_a_manager_running(
            firmware, managers="hello_world_socpuppet_iomgr.elf"
        )

        board.platform.run(LONG_ENOUGH)

        assert board.uart.output == ""


@pytest.fixture
def bootchain(firmware):
    """All three firmwares, run until the host's says how its tests went.

    Gives the story their three consoles told: `manager`, `ssd`, `host`.
    """
    # 2 MiB of drive, as in M3b, M6 and M7.
    board = host(drive_blocks=4096, manager=add_manager, drive=add_ssd)
    board.platform.build()
    # ⚠️ There are three CPUs, so say whose firmware each image is.
    board.platform.load_elf(firmware(DISK_TEST), via=board.cpu.socket)
    board.platform.load_elf(
        firmware(MANAGER_IMAGE), via=board.manager.cpu.socket
    )
    board.platform.load_elf(firmware(SSD_IMAGE), via=board.drive.ssd.cpu.socket)
    story = sp.Transcript(
        board.platform,
        {
            "manager": console_of(board),
            "ssd": board.drive.ssd.cpu_kit.uart,
            "host": board.uart,
        },
    )
    gave_a_verdict = story.run_until(
        lambda: any(
            line.who == "host" and line.text in VERDICTS for line in story.lines
        ),
        timeout=LIMIT,
    )
    assert gave_a_verdict, no_verdict(board)
    return story


@pytest.mark.platform
class TestWhenAllThreeFirmwaresBootTogether:
    def test_the_hosts_disk_test_passes(self, bootchain):
        assert "PROJECT EXECUTION SUCCESSFUL" in said_by("host", bootchain)

    def test_the_host_read_and_wrote_the_drive_that_is_the_ssds_firmware(
        self, bootchain
    ):
        # The verdict alone does not say so: a test that is skipped does
        # not spoil it.
        said = said_by("host", bootchain)

        assert any("PASS - [disk_driver.test_read]" in line for line in said)
        assert any("PASS - [disk_driver.test_write]" in line for line in said)

    def test_the_manager_says_the_link_is_up_and_the_die_released_before_the_hosts_first_line(
        self, bootchain
    ):
        # This is the order the consoles tell it in. That the host cannot
        # run any sooner is held by the `hello_world` tests in this file:
        # there the host would speak within a millisecond if nothing held
        # it, where Zephyr's disk test is a tenth of a second finding its
        # voice.
        first_line = when_first_heard("host", bootchain)

        assert when("manager", LINK_UP, bootchain) < first_line
        assert when("manager", RELEASED, bootchain) < first_line

    def test_the_ssd_says_its_drive_is_up_before_the_host_reports_its_size(
        self, bootchain
    ):
        # The host learns the size by asking the drive, and the SSD's
        # firmware is what answers.
        assert when("ssd", SSD_BANNER, bootchain) < (
            when("host", "Disk reports", bootchain)
        )


def said_by(who, story):
    """What `who` said, a line at a time."""
    return [line.text for line in story.lines if line.who == who]


def when_first_heard(who, story):
    """The simulated time `who`'s first line was finished at."""
    return min(line.time for line in story.lines if line.who == who)


def when(who, said, story):
    """The simulated time of the first line of `who`'s with `said` in it."""
    times = [
        line.time
        for line in story.lines
        if line.who == who and said in line.text
    ]
    assert times, f"{who} never said {said!r}. It said: {said_by(who, story)}"
    return min(times)


@pytest.mark.platform
class TestWhenTheLinkIsTracedWhileTheManagersFirmwareLetsTheHostGo:
    def test_neither_die_sends_the_other_anything_until_then(self, firmware):
        # `hello_world` sets its UART up, on the other die, before half a
        # millisecond of its CPU's time has gone. Zephyr's disk test is a
        # tenth of a second getting to the other die, so with that on the
        # host a link that held nothing back would show nothing here.
        board = host_with_a_manager_running(firmware, trace=True)

        board.platform.run_until(
            lambda: GREETING in board.uart.output, timeout=LONG_ENOUGH
        )

        first_crossing = min(
            each.time
            for each in sent_to_the_io_die(board)
            + sent_to_the_compute_die(board)
        )
        assert when_the_host_was_let_go(board) < first_crossing


def host_with_a_manager_running(firmware, managers=MANAGER_IMAGE, trace=False):
    """The host with Zephyr's `hello_world`, and its manager with an image.

    The manager's is the firmware that brings the link up, unless a test
    gives it another.
    """
    board = host(manager=add_manager, trace=trace)
    board.platform.build()
    # ⚠️ There are two CPUs, so say whose firmware each image is.
    board.platform.load_elf(
        firmware("hello_world_socpuppet_host.elf"), via=board.cpu.socket
    )
    board.platform.load_elf(firmware(managers), via=board.manager.cpu.socket)
    return board
