"""🧵 `interact`: a terminal at a console of the platform.

What the firmware prints shows on the terminal, and what is typed there
reaches the firmware, key by key, as on a serial console. Each test runs
`interact` in a process of its own whose terminal is a pseudo-terminal
the test holds the other end of. The firmware is Zephyr's shell on the
host's UART, which prompts within milliseconds.
"""

import os
import select
import subprocess
import sys
import termios
import time

import pytest

from cast import SHELL, SHELL_PROMPT, SHELL_VERSION
from processes import environment


@pytest.fixture
def terminal(firmware):
    it = Terminal(firmware(SHELL))
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


#: What the process runs: the host with Zephyr's shell, and `interact` at
#: its UART.
INTERACTING = """
import sys

from socpuppet.boards.host import host
from socpuppet.interactive import interact

board = host()
board.platform.build()
board.platform.load_elf(sys.argv[1])
interact(board.platform, screen=[board.uart], keyboard=board.uart)
"""
#: Seconds on the wall to wait for the terminal to show something. The
#: shell prompts within a second of starting here; CI's machines, under
#: coverage and with every core busy, take several times as long, and the
#: margin costs nothing when the text comes.
PATIENCE = 10


class Terminal:
    """A pseudo-terminal, and `interact` in a process that uses it."""

    def __init__(self, image):
        self.screen = b""
        # Where the last text waited for ended: the next is looked for
        # after it.
        self.seen = 0
        self.controller, self.device = os.openpty()
        self.settings_at_the_start = self.settings()
        self.process = subprocess.Popen(
            [sys.executable, "-c", INTERACTING, str(image)],
            stdin=self.device,
            stdout=self.device,
            stderr=subprocess.PIPE,
            env=environment(),
        )

    def settings(self):
        """The terminal's settings, as `termios` has them."""
        return termios.tcgetattr(self.device)

    def exit_status(self):
        """How the process ended, once it has, within `PATIENCE`."""
        try:
            return self.process.wait(timeout=PATIENCE)
        except subprocess.TimeoutExpired:
            pytest.fail(
                f"The process was still running {PATIENCE} s later. The "
                f"terminal showed:\n{self.screen.decode(errors='replace')}"
            )

    def type(self, keys):
        os.write(self.controller, keys)

    def wait_for(self, text):
        """Read until the screen shows `text` after what was waited for last."""
        deadline = time.monotonic() + PATIENCE
        while text not in self.screen[self.seen :]:
            if self.process.poll() is not None:
                pytest.fail(
                    f"The process ended before the terminal showed {text!r}:"
                    f"\n{self.process.stderr.read().decode()}"
                )
            if time.monotonic() > deadline:
                pytest.fail(
                    f"The terminal never showed {text!r}. It showed:\n"
                    f"{self.screen.decode(errors='replace')}"
                )
            ready, _, _ = select.select([self.controller], [], [], 0.1)
            if ready:
                self.screen += os.read(self.controller, 4096)
        self.seen = self.screen.index(text, self.seen) + len(text)

    def close(self):
        self.process.kill()
        self.process.wait()
        os.close(self.controller)
        os.close(self.device)
