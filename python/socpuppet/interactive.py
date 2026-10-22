"""🧵 A terminal at a console of the platform.

`interact` runs a platform with this process's own terminal at its
consoles, as a serial console is used: what the firmware prints shows on
the terminal as it comes, and what is typed there goes to the firmware.

    board = host()
    board.platform.build()
    board.platform.load_elf("build/firmware/shell_module_socpuppet_host.elf")
    interact(board.platform, screen=[board.uart], keyboard=board.uart)

Ctrl-] (`LEAVE`) gives the terminal back.

💡 While the CPU works, the simulation runs as fast as it can. While it
sleeps, waiting for a timer or a key, the simulated clock keeps to the
wall's: a sleep of two seconds takes two, and an idle prompt costs the
machine almost nothing. 🎓 QEMU does the same with `-icount sleep=on`.
"""

import os
import select
import sys
import termios
import time
import tty
from collections.abc import Callable, Sequence
from typing import Any, Self

from socpuppet.placed import PlacedFarEnd
from socpuppet.platform import Platform
from socpuppet.time import s

#: The key that leaves: Ctrl-], as telnet and `virsh console` have it.
#: 💡 Not QEMU's Ctrl-A, which a shell's line editing takes for Home.
LEAVE = b"\x1d"
#: Seconds on the wall between two looks at the terminal while the CPU
#: works: often enough that a key seems to land at once.
LOOK_EVERY = 0.01
#: The longest a sleeping CPU is waited for in one go, in seconds on the
#: wall. Firmware with nothing to do may set its timer days ahead.
LONGEST_WAIT = 1.0


def interact(
    platform: Platform,
    *,
    screen: Sequence[PlacedFarEnd],
    keyboard: PlacedFarEnd,
    until: Callable[[], bool] = lambda: False,
    ready: Callable[[], bool] = lambda: True,
) -> None:
    """Run `platform` with this process's terminal at its consoles.

    What each console in `screen` prints is written to standard output as
    it comes, and what comes in on standard input is typed at `keyboard`.
    A terminal hands over each key as it is pressed, as a serial line
    does, and is put back as it was at the end. Ctrl-] (`LEAVE`) ends
    the run, and so does `until()` coming true, once everything printed
    has been shown. `until` is a condition, as `Platform.run_until`'s is,
    but it is looked at only when the terminal is: each time the CPU
    sleeps, and every `LOOK_EVERY` while it works. So the run may go a
    little past the moment it came true.

    What is typed before `ready()` is true is held, and typed when it
    comes true, as a person would wait for a prompt. `ready` is looked at
    as `until` is, while something is held, and once true it is to stay
    true. Input that ends, such as a pipe whose writer is done, leaves the
    run going, and then only `until` can end it.

    🎓 A CPU that works is never more than a quantum ahead of the rest of
    the platform (`Platform.quantum`), so a next moment further off than
    that is a CPU asleep. That stretch is waited out on the wall, and a
    key ends the wait.
    """
    with _Keys() as keys:
        _run(platform, screen, keyboard, until, ready, keys)


def _run(
    platform: Platform,
    screen: Sequence[PlacedFarEnd],
    keyboard: PlacedFarEnd,
    until: Callable[[], bool],
    ready: Callable[[], bool],
    keys: "_Keys",
) -> None:
    """Run `platform`, showing `screen` and typing at `keyboard`.

    The terminal is looked at each time the CPU sleeps, and every
    `LOOK_EVERY` while it works: what is new is shown, `until` is asked,
    and what was typed is typed at the keyboard.
    """
    # What was printed before goes first: the consoles' bytes bypass the
    # text layer.
    sys.stdout.flush()
    shown = [0] * len(screen)
    typist = _Typist(keyboard, ready)
    look_again = 0.0
    while True:
        ahead = platform.time_to_next_activity
        asleep = ahead is None or ahead > platform.quantum
        if not asleep and time.monotonic() < look_again:
            platform.step()
            continue
        _show(screen, shown)
        if until():
            return
        if asleep:
            typed = _wait_out(platform, ahead, keys)
        else:
            typed = keys.within(0)
            look_again = time.monotonic() + LOOK_EVERY
            platform.step()
        if LEAVE in typed:
            return
        typist.type(typed)


def _wait_out(platform: Platform, ahead: int | None, keys: "_Keys") -> bytes:
    """Wait on the wall for a sleeping CPU's next moment, `ahead` of now.

    Or for `LONGEST_WAIT`, if that is sooner or nothing is ahead. A key
    ends the wait. The platform's clock moves on as far as the wall's
    did, and gives what was typed.
    """
    wait = LONGEST_WAIT if ahead is None else min(ahead / s(1), LONGEST_WAIT)
    waited_from = time.monotonic()
    typed = keys.within(wait)
    waited = s(time.monotonic() - waited_from)
    if ahead is not None and waited >= ahead:
        platform.step()
    elif waited:
        platform.run(waited)
    return typed


def _show(screen: Sequence[PlacedFarEnd], shown: list[int]) -> None:
    """Write what each console has printed since it was last shown."""
    for at, console in enumerate(screen):
        printed = console.output_since(shown[at])
        shown[at] += len(printed)
        sys.stdout.buffer.write(printed)
    sys.stdout.buffer.flush()


class _Keys:
    """Standard input, from the moment it is entered until it is left.

    A terminal is in raw mode in between, handing over each key as it is
    pressed, and is put back as it was when it is left.

    💡 Input that has ended, such as a pipe whose writer is done, is
    always ready to read and always reads nothing, so after it ends it is
    not read again, and waiting for a key is a plain `time.sleep`.
    """

    def __init__(self) -> None:
        self._stdin = sys.stdin.fileno()
        self._settings: list[Any] | None = None
        self._ended = False

    def __enter__(self) -> Self:
        if os.isatty(self._stdin):
            self._settings = termios.tcgetattr(self._stdin)
            tty.setraw(self._stdin)
        return self

    def __exit__(self, *_: object) -> None:
        # ⚠️ At once, not once the output has drained: on macOS a
        # pseudo-terminal's output drains only as the far end reads it,
        # which a script at the far end may not be doing.
        if self._settings is not None:
            termios.tcsetattr(self._stdin, termios.TCSANOW, self._settings)

    def within(self, seconds: float) -> bytes:
        """What is typed within `seconds`, or nothing if nothing is."""
        if self._ended:
            time.sleep(seconds)
            return b""
        ready, _, _ = select.select([self._stdin], [], [], seconds)
        if not ready:
            return b""
        typed = os.read(self._stdin, 4096)
        self._ended = not typed
        return typed


class _Typist:
    """Types at `keyboard`, holding what comes before `ready()` is true.

    `ready()` is asked only while something is held and until it is true,
    since once true it stays true: asking may cost a look through
    everything a console has printed.
    """

    def __init__(
        self, keyboard: PlacedFarEnd, ready: Callable[[], bool]
    ) -> None:
        self._keyboard = keyboard
        self._ready = ready
        self._been_ready = False
        self._held = b""

    def type(self, typed: bytes) -> None:
        """Type `typed`, after what is held, or hold it with the rest."""
        self._held += typed
        if not self._held:
            return
        self._been_ready = self._been_ready or self._ready()
        if self._been_ready:
            self._keyboard.write(self._held)
            self._held = b""
