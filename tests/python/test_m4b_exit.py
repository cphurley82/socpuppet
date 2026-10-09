"""Milestone M4b's exit test: Zephyr boots on the SSD's own controller.

The board is `socpuppet_ssd`: a 32-bit RISC-V core with an SRAM, a UART, a
timer and an interrupt controller, and the SSD's three devices around it.
Its devicetree is generated from the SSD's description, as the SSD's CPU
sees it, and the firmware here was built for it by `firmware/build.sh`.

The firmware is Zephyr's `hello_world`, which knows nothing of being an
SSD. There is a host on the PCIe link, and it does nothing.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd


@pytest.mark.platform
class TestWhenZephyrsHelloWorldBootsOnTheSsdsController:
    def test_it_prints_its_greeting_with_the_boards_name(self, firmware):
        board = ssd(host=idle_host)
        board.platform.build()
        board.platform.load_elf(
            firmware("hello_world_socpuppet_ssd.elf"), via=board.ssd.cpu.socket
        )
        console = board.ssd.cpu_kit.uart
        greeting = "Hello World! socpuppet_ssd/socpuppet_rv32"

        # The greeting comes within a few milliseconds of simulated time.
        # 50 ms leaves room and still ends a run that never prints.
        board.platform.run_until(
            lambda: greeting in console.output, timeout=sp.ms(50)
        )

        assert greeting in console.output
