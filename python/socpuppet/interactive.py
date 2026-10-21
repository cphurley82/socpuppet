"""🧵 A terminal at a console of the platform.

`interact` runs a platform with this process's own terminal at its
consoles, as a serial console is used: what the firmware prints shows on
the terminal as it comes, and what is typed there goes to the firmware.

    board = host()
    board.platform.build()
    board.platform.load_elf("build/firmware/shell_module_socpuppet_host.elf")
    interact(board.platform, screen=[board.uart], keyboard=board.uart)

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
from collections.abc import Sequence

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
) -> None:
    """Run `platform` with this process's terminal at its consoles.

    What each console in `screen` prints is written to standard output as
    it comes, and what comes in on standard input is typed at `keyboard`.
    A terminal hands over each key as it is pressed, as a serial line
    does, and is put back as it was at the end. Ctrl-] (`LEAVE`) ends
    the run.

    🎓 A CPU that works is never more than a quantum ahead of the rest of
    the platform (`Platform.quantum`), so a next moment further off than
    that is a CPU asleep. That stretch is waited out on the wall, and a
    key ends the wait.
    """
    keys = sys.stdin.fileno()
    settings = termios.tcgetattr(keys) if os.isatty(keys) else None
    if settings is not None:
        tty.setraw(keys)
    try:
        _run(platform, screen, keyboard)
    finally:
        if settings is not None:
            termios.tcsetattr(keys, termios.TCSADRAIN, settings)


def _run(
    platform: Platform,
    screen: Sequence[PlacedFarEnd],
    keyboard: PlacedFarEnd,
) -> None:
    """Run `platform`, showing `screen` and typing at `keyboard`."""
    shown = [0] * len(screen)
    look_again = 0.0
    while True:
        ahead = platform.time_to_next_activity
        if ahead is None or ahead > platform.quantum:
            _show(screen, shown)
            wait = (
                LONGEST_WAIT
                if ahead is None
                else min(ahead / s(1), LONGEST_WAIT)
            )
            waited_from = time.monotonic()
            typed = _keys(wait)
            waited = s(time.monotonic() - waited_from)
            if ahead is not None and waited >= ahead:
                platform.step()
            elif waited:
                platform.run(waited)
        else:
            typed = b""
            if time.monotonic() >= look_again:
                _show(screen, shown)
                typed = _keys(0)
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


def _keys(within: float) -> bytes:
    """What is typed within `within` seconds, or nothing if nothing is."""
    typed, _, _ = select.select([sys.stdin], [], [], within)
    return os.read(sys.stdin.fileno(), 4096) if typed else b""
