"""Milestone M5b's exit test: Zephyr boots on the IO die's manager.

The board is `socpuppet_iomgr`: a 32-bit RISC-V core with an SRAM, a UART,
a timer and an interrupt controller, and the die-to-die link's registers
beside them. Its devicetree is generated from the board's description, as
the manager's own CPU sees it, and the firmware here was built for it by
`firmware/build.sh`.

The firmware is Zephyr's `hello_world`, which knows nothing of links or
dies. 🎭 The compute die is a stand-in, and stays held in reset: nothing
has trained the link, so there is nothing to let it go for.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.io_manager import io_manager


def nothing():
    """🎭 A compute die that would do nothing even if it were let go."""
    yield from ()


@pytest.mark.platform
class TestWhenZephyrsHelloWorldBootsOnTheManager:
    def test_it_prints_its_greeting_with_the_boards_name(self, firmware):
        board = io_manager(compute=nothing)
        board.platform.build()
        board.platform.load_elf(
            firmware("hello_world_socpuppet_iomgr.elf"),
            via=board.manager.socket,
        )
        assert board.cpu_kit is not None
        console = board.cpu_kit.uart
        greeting = "Hello World! socpuppet_iomgr/socpuppet_rv32"

        # The greeting comes within a few milliseconds of simulated time.
        # 50 ms leaves room and still ends a run that never prints.
        board.platform.run_until(
            lambda: greeting in console.output, timeout=sp.ms(50)
        )

        assert greeting in console.output
