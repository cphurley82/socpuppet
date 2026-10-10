"""Milestone M8's exit test: the full bootchain, three firmwares.

M7's host crossed the real die-to-die link with 🎭 a script for the
manager that brings the link up. Here the manager is the real thing: a
32-bit CPU on the IO die running the Zephyr application of
`firmware/iomgr`, which trains the link and then lets the host's CPU out
of reset.

No image is built for this. The manager's is the one M5 runs on the IO
manager board, and the host's are the ones M3's tests run.
"""

import pytest

import socpuppet as sp
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


def host_with_a_manager_running(firmware, managers=MANAGER_IMAGE):
    """The host with Zephyr's `hello_world`, and its manager with an image.

    The manager's is the firmware that brings the link up, unless a test
    gives it another.
    """
    board = host(manager=add_manager)
    board.platform.build()
    # ⚠️ There are two CPUs, so say whose firmware each image is.
    board.platform.load_elf(
        firmware("hello_world_socpuppet_host.elf"), via=board.cpu.socket
    )
    board.platform.load_elf(firmware(managers), via=board.manager.cpu.socket)
    return board
