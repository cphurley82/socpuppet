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

    Input that ends, such as a pipe whose writer is done, leaves the run
    going, and then only `until` can end it.

    🎓 A CPU that works is never more than a quantum ahead of the rest of
    the platform (`Platform.quantum`), so a next moment further off than
    that is a CPU asleep. That stretch is waited out on the wall, and a
    key ends the wait.
    """
    stdin = sys.stdin.fileno()
    settings = termios.tcgetattr(stdin) if os.isatty(stdin) else None
    if settings is not None:
        tty.setraw(stdin)
    try:
        _run(platform, screen, keyboard, until)
    finally:
        if settings is not None:
            termios.tcsetattr(stdin, termios.TCSADRAIN, settings)


def _run(
    platform: Platform,
    screen: Sequence[PlacedFarEnd],
    keyboard: PlacedFarEnd,
    until: Callable[[], bool],
) -> None:
    """Run `platform`, showing `screen` and typing at `keyboard`.

    `until` is looked at whenever the terminal is.
    """
    shown = [0] * len(screen)
    keys = _Keys()
    look_again = 0.0
    while True:
        ahead = platform.time_to_next_activity
        if ahead is None or ahead > platform.quantum:
            _show(screen, shown)
            if until():
                return
            wait = (
                LONGEST_WAIT
                if ahead is None
                else min(ahead / s(1), LONGEST_WAIT)
            )
            waited_from = time.monotonic()
            typed = keys.within(wait)
            waited = s(time.monotonic() - waited_from)
            if ahead is not None and waited >= ahead:
                platform.step()
            elif waited:
                platform.run(waited)
        else:
            typed = b""
            if time.monotonic() >= look_again:
                _show(screen, shown)
                if until():
                    return
                typed = keys.within(0)
                look_again = time.monotonic() + LOOK_EVERY
            platform.step()
        if LEAVE in typed:
            return
        if typed:
            keyboard.write(typed)


def _show(screen: Sequence[PlacedFarEnd], shown: list[int]) -> None:
    """Write what each console has printed since it was last shown."""
    for at, console in enumerate(screen):
        printed = console.output_since(shown[at])
        shown[at] += len(printed)
        sys.stdout.buffer.write(printed)
    sys.stdout.buffer.flush()


class _Keys:
    """What comes in on standard input, until it ends.

    💡 Input that has ended, such as a pipe whose writer is done, is
    always ready to read and always reads nothing, so after it ends it is
    not read again, and waiting for a key is a plain `time.sleep`.
    """

    def __init__(self) -> None:
        self._ended = False

    def within(self, seconds: float) -> bytes:
        """What is typed within `seconds`, or nothing if nothing is."""
        if self._ended:
            time.sleep(seconds)
            return b""
        ready, _, _ = select.select([sys.stdin], [], [], seconds)
        if not ready:
            return b""
        typed = os.read(sys.stdin.fileno(), 4096)
        self._ended = not typed
        return typed
