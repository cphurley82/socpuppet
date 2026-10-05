"""Milestone M3a's exit test: Zephyr boots on socpuppet's own host board.

The board is `socpuppet_host`. Its devicetree is generated from the host
platform description, and the firmware here was built for it by
`firmware/build.sh`.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.host import host


@pytest.mark.platform
class TestWhenZephyrsHelloWorldBootsOnTheHostBoard:
    def test_it_prints_its_greeting_with_the_boards_name(self, firmware):
        board = host()
        board.platform.build()
        board.platform.load_elf(firmware("hello_world_socpuppet_host.elf"))

        # The greeting comes within a few milliseconds of simulated time.
        # 50 ms leaves room and still ends a run that never prints.
        board.platform.run_until(
            lambda: "Hello World! socpuppet_host" in board.uart.output,
            timeout=sp.ms(50),
        )

        assert "Hello World! socpuppet_host" in board.uart.output


@pytest.mark.platform
class TestWhenZephyrsSynchronizationSampleRunsOnTheHostBoard:
    """Two threads take turns to print, each sleeping in between.

    Unlike hello_world, this needs the machine timer to interrupt: a
    sleeping thread is woken by the kernel's tick.
    """

    def test_its_two_threads_take_turns(self, firmware):
        board = host()
        board.platform.build()
        board.platform.load_elf(firmware("synchronization_socpuppet_host.elf"))

        # Each turn is 100 ms of work and 500 ms of sleep, so the fourth
        # greeting comes at 1.8 s and the fifth at 2.4 s.
        board.platform.run(sp.ms(2100))

        greetings = [
            line.split(":")[0]
            for line in board.uart.output.splitlines()
            if "Hello World" in line
        ]
        assert greetings == ["thread_a", "thread_b", "thread_a", "thread_b"]

    def test_a_turn_takes_six_hundred_milliseconds(self, firmware):
        board = host()
        board.platform.build()
        board.platform.load_elf(firmware("synchronization_socpuppet_host.elf"))

        def greetings():
            return board.uart.output.count("Hello World")

        board.platform.run_until(lambda: greetings() == 2, timeout=sp.ms(2000))
        second = board.platform.time
        board.platform.run_until(lambda: greetings() == 3, timeout=sp.ms(2000))
        third = board.platform.time

        # 100 ms of busy work and a 500 ms sleep, to within the kernel's
        # 10 ms tick.
        assert third - second == pytest.approx(sp.ms(600), abs=sp.ms(10))
