"""Milestone M5's exit test: the IO die's firmware trains the die-to-die
link and lets the compute die go, and 🎭 the compute-side stand-in then
reaches the IO die's memory across it.

The firmware is `firmware/iomgr`, a Zephyr application on the manager's
own RISC-V core, with socpuppet's driver for the link under it. It is
M5a's exit test with the real thing in the manager's place: what 🎭 the
script did there, Zephyr does here, and the compute die cannot tell which
it got.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.io_manager import (
    HELLO,
    SCRATCH_BASE,
    io_manager,
    one_round_trip,
)
from socpuppet.boards.manager import LINK_BASE
from socpuppet.ops import read32, wait, write32
from socpuppet.regs import ucie_link

IMAGE = "iomgr_socpuppet_iomgr.elf"
#: What the firmware says as it goes, in the order it says it.
TRAINING = "iomgr: training the D2D link"
LINK_UP = "iomgr: D2D link up"
RELEASED = "iomgr: compute die released"
WENT_DOWN = "iomgr: the D2D link went down"
WOULD_NOT_TRAIN = "iomgr: the D2D link would not train"
#: What 🎭 the compute die writes the second time it reaches across.
AGAIN = 0x0DECAF
#: Zephyr takes a few milliseconds to start, and the link five more to
#: come up. This leaves room and still ends a run that never gets there.
LONG_ENOUGH = sp.ms(100)


def break_the_link_before_anything_starts():
    """🎭 A test's hand on the IO die: the link is faulted at power-on,
    which leaves it where only a retrain gets it out of."""
    yield write32(
        LINK_BASE + ucie_link.FAULT_INJECTION, ucie_link.FAULT_INJECTION_BREAK
    )


def break_the_link_once_the_dies_are_talking():
    """🎭 A test's hand on the IO die: it faults the link, once the compute
    die has reached across it."""
    while (yield read32(SCRATCH_BASE)) != HELLO:
        yield wait(sp.us(10))
    yield write32(
        LINK_BASE + ucie_link.FAULT_INJECTION, ucie_link.FAULT_INJECTION_BREAK
    )


def a_round_trip_and_a_write_much_later():
    """🎭 A compute die that reaches across, and again after the trouble.

    It has no view of the link, so all it can do is wait. Twenty
    milliseconds is longer than the firmware takes to train a link again,
    which is UCIe's 4 ms reset hold and then the training time.
    """
    yield from one_round_trip()
    yield wait(sp.ms(20))
    yield write32(SCRATCH_BASE, AGAIN)


def a_manager_running_its_firmware(
    firmware, compute=one_round_trip, probe=None
):
    """The board with Zephyr on the manager, and 🎭 a compute die.

    `probe` is 🎭 a script given a place of its own on the IO die's bus,
    beside the manager: a test's hand on the hardware, for what no
    firmware would do to itself.
    """
    board = io_manager(compute=compute)
    if probe is not None:
        prober = board.platform.group("io").add(
            "probe", sp.ScriptedBusMaster(script=probe)
        )
        board.platform.connect(prober.socket, board.bus.add_input())
    board.platform.build()
    board.platform.load_elf(firmware(IMAGE), via=board.manager.cpu.socket)
    return board


def console_of(board):
    """The manager's console, which is where its firmware prints."""
    assert board.manager.cpu_kit is not None
    return board.manager.cpu_kit.uart


def what_the_manager_said(console):
    """The firmware's own lines, without Zephyr's banner above them."""
    return [
        line
        for line in console.output.splitlines()
        if line.startswith("iomgr:")
    ]


def what_the_manager_said_after(line, console):
    """The firmware's lines that came after the first `line`."""
    said = what_the_manager_said(console)
    return said[said.index(line) + 1 :]


def scratch_holds(board, word):
    """Whether the IO die's scratch memory has `word` in it."""
    seen = board.platform.peek32(SCRATCH_BASE, via=board.manager.cpu.socket)
    return seen == word


def until_the_round_trip_has_landed(board):
    """Runs until the compute die's word is in the IO die's scratch."""
    return board.platform.run_until(
        lambda: scratch_holds(board, HELLO), timeout=LONG_ENOUGH
    )


@pytest.mark.platform
class TestWhenTheManagersFirmwareBoots:
    def test_the_compute_die_round_trips_a_word_through_the_io_dies_memory(
        self, firmware
    ):
        board = a_manager_running_its_firmware(firmware)

        # 🎭 The round trip reads back what it wrote and says so if it
        # cannot, so landing at all is the round trip.
        assert until_the_round_trip_has_landed(board)

    def test_its_console_reads_training_then_link_up_then_released(
        self, firmware
    ):
        board = a_manager_running_its_firmware(firmware)
        console = console_of(board)

        # 💡 The compute die runs the moment it is let go, which is before
        # the manager has finished saying that it let it go.
        board.platform.run_until(
            lambda: RELEASED in console.output, timeout=LONG_ENOUGH
        )

        assert what_the_manager_said(console) == [TRAINING, LINK_UP, RELEASED]


@pytest.mark.platform
class TestWhenSomethingFaultsTheLinkUnderTheFirmware:
    def test_the_firmware_trains_it_again_and_the_dies_carry_on(self, firmware):
        board = a_manager_running_its_firmware(
            firmware,
            compute=a_round_trip_and_a_write_much_later,
            probe=break_the_link_once_the_dies_are_talking,
        )

        board.platform.run_until(
            lambda: scratch_holds(board, AGAIN), timeout=LONG_ENOUGH
        )

        assert scratch_holds(board, AGAIN)

    def test_the_firmware_says_the_link_went_down_and_came_back(self, firmware):
        board = a_manager_running_its_firmware(
            firmware, probe=break_the_link_once_the_dies_are_talking
        )
        console = console_of(board)

        board.platform.run_until(
            lambda: console.output.count(LINK_UP) == 2, timeout=LONG_ENOUGH
        )

        assert what_the_manager_said_after(RELEASED, console) == [
            WENT_DOWN,
            LINK_UP,
        ]


@pytest.mark.platform
class TestWhenTheLinkWillNotTrain:
    def test_the_firmware_says_so_and_the_compute_die_stays_in_reset(
        self, firmware
    ):
        board = a_manager_running_its_firmware(
            firmware, probe=break_the_link_before_anything_starts
        )
        console = console_of(board)

        # The firmware gives a link a tenth of a second to come up.
        board.platform.run_until(
            lambda: WOULD_NOT_TRAIN in console.output, timeout=sp.ms(300)
        )

        assert WOULD_NOT_TRAIN in console.output
        assert scratch_holds(board, 0)
