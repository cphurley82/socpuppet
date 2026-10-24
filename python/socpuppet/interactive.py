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
machine almost nothing. 💡 The terminal is a far end that
`socpuppet.pump` keeps up with, and the pump is what keeps the simulated
clock to the wall's.
"""

import os
import sys
import termios
import tty
from collections.abc import Callable, Sequence
from typing import Any, Self

from socpuppet.placed import PlacedFarEnd
from socpuppet.platform import Platform
from socpuppet.pump import pump

#: The key that leaves: Ctrl-], as telnet and `virsh console` have it.
#: 💡 Not QEMU's Ctrl-A, which a shell's line editing takes for Home.
LEAVE = b"\x1d"


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
    sleeps, and every `socpuppet.pump.LOOK_EVERY` while it works. So the
    run may go a little past the moment it came true.

    What is typed before `ready()` is true is held, and typed when it
    comes true, as a person would wait for a prompt. `ready` is looked at
    as `until` is, while something is held, and once true it is to stay
    true. Input that ends, such as a pipe whose writer is done, leaves the
    run going, and then only `until` can end it. Output that ends, such as
    a pipe whose reader has gone, ends the run: the `BrokenPipeError` is
    raised on, once the terminal is put back, for the caller to say so.
    """
    # What was printed before goes first: the consoles' bytes bypass the
    # text layer.
    sys.stdout.flush()
    terminal = _Terminal(screen, keyboard, ready)
    with _RawMode():
        pump(
            platform,
            far_ends=[terminal],
            until=lambda: terminal.left or until(),
        )


class _Terminal:
    """This process's terminal, as a far end the platform is pumped with.

    What comes in on standard input is typed at `keyboard`, as `_Typist`
    types, and what each console in `screen` prints is shown on standard
    output at each look. `left` is whether `LEAVE` has been typed.

    💡 Input that has ended, such as a pipe whose writer is done, is
    always ready to read and always reads nothing, so after it ends it is
    not waited on again.
    """

    def __init__(
        self,
        screen: Sequence[PlacedFarEnd],
        keyboard: PlacedFarEnd,
        ready: Callable[[], bool],
    ) -> None:
        self._stdin = sys.stdin.fileno()
        self._ended = False
        self._screen = screen
        self._shown = [0] * len(screen)
        self._typist = _Typist(keyboard, ready)
        self.left = False

    def fileno(self) -> int | None:
        return None if self._ended else self._stdin

    def due_in(self) -> None:
        return None

    def service(self) -> None:
        typed = os.read(self._stdin, 4096)
        self._ended = not typed
        if LEAVE in typed:
            self.left = True
        else:
            self._typist.type(typed)

    def refresh(self) -> None:
        for at, console in enumerate(self._screen):
            printed = console.output_since(self._shown[at])
            self._shown[at] += len(printed)
            sys.stdout.buffer.write(printed)
        sys.stdout.buffer.flush()
        self._typist.catch_up()


class _RawMode:
    """Standard input in raw mode, if it is a terminal, while this is in.

    A terminal in raw mode hands over each key as it is pressed. It is put
    back as it was when this is left.
    """

    def __init__(self) -> None:
        self._stdin = sys.stdin.fileno()
        self._settings: list[Any] | None = None

    def __enter__(self) -> Self:
        if os.isatty(self._stdin):
            self._settings = termios.tcgetattr(self._stdin)
            # ⚠️ At once, keeping what was typed already: `setraw`'s own
            # default, TCSAFLUSH, throws away the keys pressed while the
            # platform was being built, which are meant to wait for the
            # prompt.
            tty.setraw(self._stdin, termios.TCSANOW)
        return self

    def __exit__(self, *_: object) -> None:
        # ⚠️ At once, not once the output has drained: on macOS a
        # pseudo-terminal's output drains only as the far end reads it,
        # which a script at the far end may not be doing.
        if self._settings is not None:
            termios.tcsetattr(self._stdin, termios.TCSANOW, self._settings)


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
        self.catch_up()

    def catch_up(self) -> None:
        """Type what is held, if the firmware is ready for it now."""
        if not self._held:
            return
        self._been_ready = self._been_ready or self._ready()
        if self._been_ready:
            self._keyboard.write(self._held)
            self._held = b""
