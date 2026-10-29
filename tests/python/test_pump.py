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
from socpuppet.pump import LONGEST_WAIT, PumpedFarEnd, pump
from socpuppet.time import ms, ns, s, us

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
    descriptor was readable, and "refresh" at each look. `looked_at` is
    when each look came, on the wall.
    """

    def __init__(self) -> None:
        self._read, self._write = os.pipe()
        self.events: list[str] = []
        self.looked_at: list[float] = []
        self._writer: threading.Timer | None = None
        self._write_times: tuple[float, float] | None = None
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
        self.looked_at.append(time.monotonic())

    def write_after(self, seconds: float) -> None:
        """Write a byte to the pipe `seconds` from now."""
        self._writer = threading.Timer(seconds, self._write_a_byte)
        self._writer.start()

    def write_times(self) -> tuple[float, float]:
        """On the wall, just before the byte was written and just after.

        ⚠️ The pump can service the byte before the timer's thread gets
        round to its second stamp, so this waits for the thread.
        """
        assert self._writer is not None
        self._writer.join(PATIENCE)
        assert self._write_times is not None
        return self._write_times

    def was_refreshed_after_its_service(self) -> bool:
        return self.events[-2:] == ["service", "refresh"]

    def looks_between_the_write_and_its_service(self) -> int:
        """How many looks came between the byte's write and its service.

        None, or the one that found it.
        """
        _, written_at = self.write_times()
        assert self.serviced_at is not None
        return sum(written_at < at < self.serviced_at for at in self.looked_at)

    def close(self) -> None:
        os.close(self._read)
        os.close(self._write)

    def _write_a_byte(self) -> None:
        # No look can find the byte before the first stamp, and a look
        # after the second could have.
        before = time.monotonic()
        os.write(self._write, b"x")
        self._write_times = (before, time.monotonic())


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
        written, _ = pipe.write_times()
        assert platform.time >= s(written - started) - s(SLACK)


class TestWhenAFarEndsDescriptorBecomesReadableWhileTheCpuWorks:
    def test_it_is_serviced_at_the_first_look_that_finds_it(self, pipe):
        platform = a_platform_whose_cpu(works)
        pipe.write_after(WRITTEN_AFTER)

        assert pumped_until(platform, pipe, lambda: "service" in pipe.events)
        assert pipe.looks_between_the_write_and_its_service() <= 1
        # 💡 The looks come every LOOK_EVERY, but a busy Mac of CI's has
        # taken 0.12 s from the write to the service. So, as for a due far
        # end below, the bound is half the longest wait: a pump that looked
        # only once that was up would fail it.
        written, _ = pipe.write_times()
        assert pipe.serviced_at - written < LONGEST_WAIT / 2


class TestWhenAFarEndHasBeenServiced:
    def test_it_is_refreshed_before_the_until_condition_is_asked(self, pipe):
        platform = a_platform_whose_cpu(sleeps)
        pipe.write_after(WRITTEN_AFTER)

        assert pumped_until(
            platform, pipe, pipe.was_refreshed_after_its_service
        )


class TestWhenAFarEndIsDueWhileTheCpuSleeps:
    def test_it_is_refreshed_before_the_longest_wait_is_up(self):
        platform = a_platform_whose_cpu(sleeps)
        alarm = Alarm(DUE_IN)

        assert pumped_until(platform, alarm, lambda: alarm.rang_at is not None)
        # 💡 A pump that took no notice of it would look again only once
        # the longest wait was up, the CPU sleeping for longer. Half of it
        # is room for a busy Mac of CI's, which has taken 0.18 s over a
        # wait of 0.05.
        assert alarm.rang_at - alarm.set_at < LONGEST_WAIT / 2


class TestWhenThereIsNoFarEnd:
    def test_a_sleeping_cpu_is_waited_for_on_the_wall(self):
        platform = a_platform_whose_cpu(sleeps)
        started = time.monotonic()

        pump(platform, until=lambda: time.monotonic() - started >= 0.3)

        assert s(0.3) <= platform.time <= s(time.monotonic() - started)


class TestWhenACpusNextStepIsJustPastTheQuantum:
    def test_it_is_taken_as_working_and_its_clock_runs_ahead_of_the_wall(
        self,
    ):
        # 🎓 QBox's hart ends each quantum at the end of a translation
        # block, a few instructions past the quantum: that is a CPU hard
        # at work, not one asleep.
        # 💡 A tenth of a second a step: taken as asleep, each step would
        # be waited out on the wall and the second would take a second.
        quantum = ms(100)
        platform = a_platform_whose_cpu(
            steps_just_past(quantum), quantum=quantum
        )
        started = time.monotonic()

        pump(platform, until=lambda: platform.time >= s(1))

        assert platform.time > 2 * s(time.monotonic() - started)


def a_platform_whose_cpu(script: Callable, quantum: int = us(1)) -> sp.Platform:
    """A platform with one bus master, running `script`, and its memory."""
    platform = sp.Platform()
    platform.quantum = quantum
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


def steps_just_past(quantum: int) -> Callable:
    """A CPU whose every step is a microsecond past `quantum`."""

    def script():
        while True:
            yield wait(quantum + us(1))

    return script


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
