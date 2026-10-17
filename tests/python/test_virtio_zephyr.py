"""Zephyr's own virtio drivers against 🎭 the host's virtio devices.

The drivers nobody here wrote are the point: each image is one of Zephyr's
own tests or samples, built for `socpuppet_host` with the shield
`socpuppet_host_virtio`, which puts the devices on the host's IO die.

    compute.cpu ─▶ ... ─▶ io.bus ─┬─▶ io.uart        (the console)
                                  └─▶ io.rng.cpu    (slot 0)
    compute.ram ◀── link ◀── io.up ◀── io.rng.dma
    compute.imsic ◀── link ◀── io.aplic ◀── io.rng.irq (source 18)
"""

import pytest

import socpuppet as sp
from cast import boot
from socpuppet import ztest
from socpuppet.boards.host import host
from socpuppet.boards.virtio import Virtio

pytestmark = pytest.mark.long

#: Zephyr's `tests/drivers/entropy/api`, with the shield.
ENTROPY_API = "entropy_api_socpuppet_host.elf"
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
