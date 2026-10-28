"""🐧 Linux takes the host's GPIO, as part of M18's.

The GPIO is SiFive's, on the host's IO die, with four pins brought out. A
stock kernel's own driver, `gpio-sifive`, takes it as a GPIO chip with a
line for each pin. Busybox has no GPIO tools, so nothing here drives a
pin from Linux: Zephyr's half (`test_m18_exit.py`) does that.
"""

import pytest

from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    a_host_with_linux,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)
from socpuppet.boards.host import GPIO_OFFSET, GPIO_PINS, IO_BASE

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. A boot
#: of Linux takes seconds on QBox's hart and minutes on the interpreter, so
#: the tests are handed out first.
pytestmark = [needs_dtc, pytest.mark.long, pytest.mark.platform]


@pytest.fixture
def linux_at_its_prompt(firmware):
    """A host booted to Linux's prompt."""
    board = a_host_with_linux(firmware)
    prompted = run_to_the_prompt(board)
    assert prompted, (
        "Linux never prompted. OpenSBI's console:\n"
        f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
        f"{plain(board.virtio.console.output)[-3000:]}"
    )
    return board


class TestWhenLinuxBootsOnTheHost:
    def test_gpio_sifive_takes_the_gpio_with_a_line_for_each_pin(
        self, linux_at_its_prompt
    ):
        # 🎓 The kernel says what GPIO chips it has in debugfs, its file
        # system of what its drivers want to show, which busybox's init
        # leaves unmounted.
        board = linux_at_its_prompt
        device = f"{IO_BASE + GPIO_OFFSET:x}.gpio"

        type_and_wait_for_the_prompt(
            board, "mount -t debugfs none /sys/kernel/debug"
        )
        chips = type_and_wait_for_the_prompt(
            board, "cat /sys/kernel/debug/gpio"
        )

        assert f"{GPIO_PINS} GPIOs, parent: platform/{device}" in chips
