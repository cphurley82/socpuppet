"""🐧 Linux sets its clock from the host's real-time clock, as part of M18's.

The clock is the Goldfish real-time clock, on the host's IO die, given a
time as the simulation starts. A stock kernel's own driver, `rtc-goldfish`,
takes it as `rtc0`, and the kernel sets the system's clock from it as it
boots (`RTC_HCTOSYS`). Zephyr's half is in `test_zephyr_peripheral_samples.py`.
"""

import datetime

import pytest

import socpuppet as sp
from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    a_host_with_linux,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. A boot
#: of Linux takes seconds on QBox's hart and minutes on the interpreter, so
#: the tests are handed out first.
pytestmark = [needs_dtc, pytest.mark.long, pytest.mark.platform]

#: The time the clock is given: a day that is no simulation's start.
GIVEN = datetime.datetime(2026, 10, 26, tzinfo=datetime.UTC)
#: 🎓 The kernel sets its clock half a second past the whole second it reads
#: from the real-time clock (`rtc_hctosys`), so the date can be a second
#: ahead of the simulated time in whole seconds.
ROUNDING = 1


@pytest.fixture
def linux_at_its_prompt(firmware):
    """A host whose clock was given GIVEN, booted to Linux's prompt."""
    board = a_host_with_linux(firmware, rtc_time=GIVEN)
    prompted = run_to_the_prompt(board)
    assert prompted, (
        "Linux never prompted. OpenSBI's console:\n"
        f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
        f"{plain(board.virtio.console.output)[-3000:]}"
    )
    return board


class TestWhenLinuxBootsOnAHostWhoseClockWasGivenATime:
    def test_rtc_goldfish_takes_the_clock_as_rtc0(self, linux_at_its_prompt):
        name = type_and_wait_for_the_prompt(
            linux_at_its_prompt, "cat /sys/class/rtc/rtc0/name"
        )

        assert "goldfish" in name

    def test_the_date_is_the_given_time_and_the_simulated_time_since(
        self, linux_at_its_prompt
    ):
        # 🎓 `date` asks the system's clock, which the kernel set from the
        # real-time clock as it booted, and which has counted on since.
        board = linux_at_its_prompt

        date = int(type_and_wait_for_the_prompt(board, "date +%s"))
        simulated = board.platform.time // sp.ms(1000)

        given = int(GIVEN.timestamp())
        assert given <= date <= given + simulated + ROUNDING
