"""🧵 `pump`: a run that keeps up with what is outside the simulation.

A far end outside, such as this machine's /dev/pciem or a socket, says
when it has something by its file descriptor becoming readable. The pump
waits on the far ends' descriptors while the platform sleeps, looks at
them while it works, services each one that is readable, and refreshes
each, at each look, with what the platform has done. Here the far end is
a pipe, which a timer writes to while the platform runs. A far end may
also be due: it has something to do at a moment on the wall, such as a
timer of its own, and the pump looks at it by then.
"""

import os
import threading
import time
from collections.abc import Callable

import pytest

import socpuppet as sp
from socpuppet.ops import wait
from socpuppet.pump import LONGEST_WAIT, LOOK_EVERY, PumpedFarEnd, pump
from socpuppet.time import ns, s, us

pytestmark = pytest.mark.platform

#: How long after it is asked for the pipe is written to, in seconds on
#: the wall: long enough that the pump is already waiting or working when
#: the byte arrives, so that it is noticed and not found at the first look.
WRITTEN_AFTER = 0.2
#: How much later than a look a busy machine may get round to it.
SLACK = 0.05
#: How long, on the wall, a test waits for what it waits for, so that
#: something that never comes fails the test and does not hang it.
PATIENCE = 5.0


class Pipe:
    """A far end that is a pipe: what is written to it is serviced.

    `events` is what the pump did with it, in order: "service" when its
    descriptor was readable, and "refresh" at each look.
    """

    def __init__(self) -> None:
        self._read, self._write = os.pipe()
        self.events: list[str] = []
        self.written_at: float | None = None
        self.serviced_at: float | None = None

    def fileno(self) -> int | None:
        return self._read

    def due_in(self) -> float | None:
        return None

    def service(self) -> None:
        os.read(self._read, 4096)
        self.events.append("service")
        self.serviced_at = time.monotonic()

    def refresh(self) -> None:
        self.events.append("refresh")

    def write_after(self, seconds: float) -> None:
        """Write a byte to the pipe `seconds` from now."""
        threading.Timer(seconds, self._write_a_byte).start()

    def was_refreshed_after_its_service(self) -> bool:
        return self.events[-2:] == ["service", "refresh"]

    def close(self) -> None:
        os.close(self._read)
        os.close(self._write)

    def _write_a_byte(self) -> None:
        self.written_at = time.monotonic()
        os.write(self._write, b"x")


#: How far ahead of now, in seconds on the wall, an alarm is due: much
#: sooner than the longest the pump waits for a sleeping CPU.
DUE_IN = LONGEST_WAIT / 20


class Alarm:
    """A far end with no descriptor, due `seconds` after it is made.

    `rang_at` is when it was first refreshed once due, on the wall.
    """

    def __init__(self, seconds: float) -> None:
        self.set_at = time.monotonic()
        self._rings_at = self.set_at + seconds
        self.rang_at: float | None = None

    def fileno(self) -> int | None:
        return None

    def due_in(self) -> float | None:
        if self.rang_at is not None:
            return None
        return max(0.0, self._rings_at - time.monotonic())

    def service(self) -> None:
        raise AssertionError("an alarm has no descriptor to be readable")

    def refresh(self) -> None:
        now = time.monotonic()
        if self.rang_at is None and now >= self._rings_at:
            self.rang_at = now


@pytest.fixture
def pipe():
    it = Pipe()
    yield it
    it.close()


class TestWhenAFarEndsDescriptorBecomesReadableWhileTheCpuSleeps:
    def test_it_is_serviced_and_the_clock_has_moved_only_as_far_as_the_wall(
        self, pipe
    ):
        platform = a_platform_whose_cpu(sleeps)
        started = time.monotonic()
        pipe.write_after(WRITTEN_AFTER)

        assert pumped_until(platform, pipe, lambda: "service" in pipe.events)
        assert platform.time <= s(time.monotonic() - started)
        assert platform.time >= s(pipe.written_at - started) - s(SLACK)


class TestWhenAFarEndsDescriptorBecomesReadableWhileTheCpuWorks:
    def test_it_is_serviced_within_a_look(self, pipe):
        platform = a_platform_whose_cpu(works)
        pipe.write_after(WRITTEN_AFTER)

        assert pumped_until(platform, pipe, lambda: "service" in pipe.events)
        assert pipe.serviced_at - pipe.written_at < LOOK_EVERY + SLACK


class TestWhenAFarEndHasBeenServiced:
    def test_it_is_refreshed_before_the_until_condition_is_asked(self, pipe):
        platform = a_platform_whose_cpu(sleeps)
        pipe.write_after(WRITTEN_AFTER)

        assert pumped_until(
            platform, pipe, pipe.was_refreshed_after_its_service
        )


class TestWhenAFarEndIsDueWhileTheCpuSleeps:
    def test_it_is_refreshed_by_then(self):
        platform = a_platform_whose_cpu(sleeps)
        alarm = Alarm(DUE_IN)

        assert pumped_until(platform, alarm, lambda: alarm.rang_at is not None)
        assert alarm.rang_at - alarm.set_at < DUE_IN + SLACK


class TestWhenThereIsNoFarEnd:
    def test_a_sleeping_cpu_is_waited_for_on_the_wall(self):
        platform = a_platform_whose_cpu(sleeps)
        started = time.monotonic()

        pump(platform, until=lambda: time.monotonic() - started >= 0.3)

        assert s(0.3) <= platform.time <= s(time.monotonic() - started)


def a_platform_whose_cpu(script: Callable) -> sp.Platform:
    """A platform with one bus master, running `script`, and its memory."""
    platform = sp.Platform()
    platform.quantum = us(1)
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script=script))
    ram = platform.add("ram", sp.Memory(size=0x100))
    platform.connect(cpu.socket, ram.socket)
    platform.build()
    return platform


def sleeps():
    """A CPU with nothing to do for ten seconds of its clock."""
    yield wait(s(10))


def works():
    """A CPU that is never more than a nanosecond from its next step."""
    while True:
        yield wait(ns(1))


def pumped_until(
    platform: sp.Platform, far_end: PumpedFarEnd, condition
) -> bool:
    """Pump `platform` with `far_end` until `condition`, or PATIENCE runs out.

    Returns whether `condition` came true.
    """
    started = time.monotonic()
    pump(
        platform,
        far_ends=[far_end],
        until=lambda: condition() or time.monotonic() - started > PATIENCE,
    )
    return condition()
