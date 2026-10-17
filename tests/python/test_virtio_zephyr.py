"""Zephyr's own virtio drivers against 🎭 the host's virtio devices.

The drivers nobody here wrote are the point: each image is one of Zephyr's
own tests or samples, built for `socpuppet_host` with the shield
`socpuppet_host_virtio`, which puts the devices on the host's IO die.

    compute.cpu ─▶ ... ─▶ io.bus ─┬─▶ io.uart           (the console)
                                  ├─▶ io.rng.cpu       (slot 0)
                                  └─▶ io.console.cpu   (slot 1)
    compute.ram ◀── link ◀── io.up ◀── io.rng.dma, io.console.dma
    compute.imsic ◀── link ◀── io.aplic ◀── io.rng.irq     (source 18)
                                       ◀── io.console.irq (source 19)

A second shield, `socpuppet_host_virtio_console`, makes the virtio console
Zephyr's console in place of the UART.
"""

import pytest

import socpuppet as sp
from cast import GREETING, boot
from socpuppet import ztest
from socpuppet.boards.host import host
from socpuppet.boards.virtio import Virtio

pytestmark = pytest.mark.long

#: Zephyr's `tests/drivers/entropy/api`, with the shield.
ENTROPY_API = "entropy_api_socpuppet_host.elf"
#: Zephyr's `samples/hello_world`, with the shield and a second one that
#: makes the virtio console Zephyr's console.
HELLO_VIRTIO_CONSOLE = "hello_virtio_console_socpuppet_host.elf"
#: The verdict comes well inside a second of simulated time; 2 s still
#: ends a run that never gives one.
LIMIT = sp.ms(2000)


def run_to_a_verdict(board):
    """Run until the host's firmware says how its tests went.

    Returns what it said of them, as a `socpuppet.ztest.Report`.
    """
    gave_a_verdict = board.platform.run_until(
        lambda: ztest.verdict_of(board.uart.output) is not None,
        timeout=LIMIT,
    )
    assert gave_a_verdict, (
        "The host's firmware gave no verdict in the time it was given. "
        f"It printed:\n{board.uart.output or '(nothing)'}"
    )
    return ztest.parse(board.uart.output)


@pytest.mark.platform
class TestWhenZephyrsEntropyApiTestRunsOnTheVirtioEntropyDevice:
    def test_its_one_case_passes_through_zephyrs_own_virtio_driver(
        self, firmware
    ):
        board = host(virtio=Virtio())
        boot(board, firmware, host=ENTROPY_API)

        report = run_to_a_verdict(board)

        assert report.case("entropy_api.test_entropy_get_entropy").result == (
            "PASS"
        ), f"The host's firmware printed:\n{board.uart.output}"


@pytest.mark.platform
class TestWhenZephyrsConsoleIsTheVirtioConsole:
    def test_the_greeting_comes_through_the_virtio_console_alone(
        self, firmware
    ):
        board = host(virtio=Virtio())
        boot(board, firmware, host=HELLO_VIRTIO_CONSOLE)
        console = board.virtio.console

        greeted = board.platform.run_until(
            lambda: GREETING in console.output, timeout=LIMIT
        )

        assert greeted, (
            "No greeting came through the virtio console. It said "
            f"{console.output!r}, and the UART {board.uart.output!r}."
        )
        assert board.uart.output == ""
