"""🧵 `interact`: a terminal at a console of the platform.

What the firmware prints shows on the terminal, and what is typed there
reaches the firmware, key by key, as on a serial console. Each test runs
`interact` in a process of its own whose terminal is a pseudo-terminal
the test holds the other end of. The firmware is Zephyr's shell on the
host's UART, which prompts within milliseconds.
"""

import contextlib
import resource
import subprocess
import sys
import time
from typing import NamedTuple

import pytest

from cast import SHELL, SHELL_PROMPT, SHELL_VERSION
from processes import ended_or_killed, environment, unmeasured
from pseudo_terminal import Terminal
from socpuppet.time import s


@pytest.fixture
def terminal(firmware):
    it = Terminal(["-c", SHELL_ONLY, str(firmware(SHELL))], patience=PATIENCE)
    yield it
    it.close()


@pytest.fixture
def terminal_until_answered(firmware):
    it = Terminal(
        ["-c", UNTIL_ANSWERED, str(firmware(SHELL))], patience=PATIENCE
    )
    yield it
    it.close()


class TestWhenSomeoneTypesAtTheTerminal:
    def test_the_firmware_answers_on_it(self, terminal):
        terminal.wait_for(SHELL_PROMPT.encode())

        # Enter, on a terminal that hands over each key, is a carriage
        # return.
        terminal.type(b"kernel version\r")

        terminal.wait_for(SHELL_VERSION.encode())

    def test_a_key_reaches_the_firmware_without_waiting_for_enter(
        self, terminal
    ):
        terminal.wait_for(SHELL_PROMPT.encode())

        # Tab asks the shell to finish the word, and `kernel` is the one
        # command that starts `kern`. A terminal that kept the line until
        # Enter would show only what was typed.
        terminal.type(b"kern\t")

        terminal.wait_for(b"kernel")


class TestWhenSomeonePressesCtrlRightBracket:
    def test_interact_returns_and_the_terminal_is_as_it_was(self, terminal):
        # 🎓 Ctrl-] is the key telnet and `virsh console` leave by.
        terminal.wait_for(SHELL_PROMPT.encode())

        terminal.type(b"\x1d")

        assert terminal.exit_status() == 0
        assert terminal.settings() == terminal.settings_at_the_start


class TestWhenTheUntilConditionComesTrue:
    def test_interact_returns_having_shown_everything_printed(
        self, terminal_until_answered
    ):
        terminal = terminal_until_answered
        terminal.wait_for(SHELL_PROMPT.encode())

        terminal.type(b"kernel version\r")

        assert terminal.exit_status() == 0
        terminal.wait_for(SHELL_VERSION.encode())


class TestWhenKeysComeBeforeTheReadyConditionIsTrue:
    def test_they_are_held_until_it_is(self, firmware):
        said = standard_error(
            HELD_UNTIL_READY, firmware(SHELL), typed=b"kernel version\n"
        )

        assert returned_at(said) >= READY_AFTER


class TestWhenTheReaderOfPipedOutputHasGone:
    def test_the_run_ends_and_interact_raises_the_broken_pipe(self, firmware):
        # 🎓 `socpuppet linux | head -1`: head leaves with its line, and
        # the next thing the console prints has nowhere to go.
        with started(READER_GONE, firmware(SHELL)) as run:
            run.stdout.readline()
            run.stdout.close()
            # Something to print after the reader has gone, which is the
            # only way out: the script has no `until`.
            type_at(run, b"kernel version\n")

            ended = run.wait(timeout=PATIENCE)

            said = run.stderr.read().decode()
            assert ended == 0, said
            assert "the reader has gone" in said


class TestWhenPipedInputHasEndedAndTheCpuSleeps:
    def test_the_run_waits_without_keeping_this_machine_busy(self, firmware):
        # The shell answers and sleeps, and the run goes on for IDLE
        # seconds of the CPU's clock.
        start_up = piped(UNTIL_STARTED, firmware(SHELL), typed=b"")
        run = piped(UNTIL_IDLE, firmware(SHELL), typed=b"kernel version\n")

        # The CPU's clock keeps to the wall's while it sleeps.
        assert run.wall >= IDLE
        # What starting Python and building the platform cost depends on
        # the build, seconds under coverage's -O0, so it is taken off;
        # waiting by spinning would cost all IDLE seconds.
        assert run.busy - start_up.busy < IDLE / 2


#: What the process runs: the host with Zephyr's shell, and `interact` at
#: its UART, with `options` or without, and `after` it, if anything.
INTERACTING = """
import sys

from socpuppet.boards.host import host
from socpuppet.interactive import interact

board = host()
board.platform.build()
board.platform.load_elf(sys.argv[1])
interact(board.platform, screen=[board.uart], keyboard=board.uart{options})
{after}
"""
SHELL_ONLY = INTERACTING.format(options="", after="")
#: The same, until IDLE seconds of the CPU's clock have passed. Long
#: enough that a wait that spins (a second of this machine's CPU each
#: second) stands well clear of how much starting up costs from one run
#: to the next, and short enough for one long test.
IDLE = 4
UNTIL_IDLE = INTERACTING.format(
    options=f", until=lambda: board.platform.time >= {s(IDLE)}", after=""
)
#: The same, ending at its first look at the terminal: what starting up
#: costs, and no more.
UNTIL_STARTED = INTERACTING.format(options=", until=lambda: True", after="")
#: The same, until the shell has answered `kernel version`.
ANSWERED = f"lambda: {SHELL_VERSION!r} in board.uart.output"
UNTIL_ANSWERED = INTERACTING.format(options=f", until={ANSWERED}", after="")
#: The same, with keys held until a second of the CPU's clock has passed,
#: saying when it returned, in picoseconds. It returns once the shell has
#: answered, so the shell had not answered before then.
READY_AFTER = s(1)
HELD_UNTIL_READY = INTERACTING.format(
    options=(
        f", until={ANSWERED}"
        f", ready=lambda: board.platform.time >= {READY_AFTER}"
    ),
    after='print(f"returned at {board.platform.time}", file=sys.stderr)',
)
#: The same, with no `until`, saying on standard error if the reader of
#: its output has gone, and ending there: the interpreter's own last flush
#: of standard output would otherwise fail the same way.
READER_GONE = """
import os
import sys

from socpuppet.boards.host import host
from socpuppet.interactive import interact

board = host()
board.platform.build()
board.platform.load_elf(sys.argv[1])
try:
    interact(board.platform, screen=[board.uart], keyboard=board.uart)
except BrokenPipeError:
    print("the reader has gone", file=sys.stderr)
    os._exit(0)
"""
#: Seconds on the wall to wait for the terminal to show something. The
#: shell prompts within a second of starting here; CI's machines, under
#: coverage and with every core busy, take several times as long, and the
#: margin costs nothing when the text comes.
PATIENCE = 10


class Timed(NamedTuple):
    """How long a process took on the wall, and of this machine's CPU."""

    wall: float
    busy: float


def piped(script, image, typed):
    """Run `script` with `typed` piped to it, and time it.

    The process is left alone by coverage.py, which would add CPU time of
    its own.
    """
    busy_before, wall_before = cpu_seconds_of_children(), time.monotonic()
    ran = subprocess.run(
        [sys.executable, "-c", script, str(image)],
        input=typed,
        capture_output=True,
        env=unmeasured(environment()),
        timeout=IDLE + PATIENCE,
    )
    assert ran.returncode == 0, ran.stderr.decode()
    return Timed(
        wall=time.monotonic() - wall_before,
        busy=cpu_seconds_of_children() - busy_before,
    )


def started(script, image):
    """Start `script` with its input and output piped, and give the process.

    It is killed when the `with` ends, if it is still running.
    """
    return ended_or_killed(
        subprocess.Popen(
            [sys.executable, "-c", script, str(image)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment(),
        )
    )


def type_at(run, typed):
    """Type `typed` at `run`'s piped standard input, and end the input.

    A run that has already ended, as the test may want it to, has nothing
    to type at: that is no failure.
    """
    with contextlib.suppress(BrokenPipeError):
        run.stdin.write(typed)
        run.stdin.close()


def cpu_seconds_of_children():
    """The CPU time of the processes this one has started and waited for."""
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def standard_error(script, image, typed):
    """Run `script` with `typed` piped to it; give what it wrote to stderr."""
    ran = subprocess.run(
        [sys.executable, "-c", script, str(image)],
        input=typed,
        capture_output=True,
        env=environment(),
        timeout=PATIENCE,
    )
    assert ran.returncode == 0, ran.stderr.decode()
    return ran.stderr.decode()


def returned_at(said):
    """When `interact` returned, by the line HELD_UNTIL_READY prints."""
    (line,) = (
        each for each in said.splitlines() if each.startswith("returned at ")
    )
    return int(line.removeprefix("returned at "))
