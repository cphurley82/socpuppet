"""A pseudo-terminal, with a Python process at the far end of it.

🎓 A pseudo-terminal is a pair of ends that behave as a terminal and the
keyboard and screen in front of it. The process gets the device end as its
standard input and output, and a test holds the other end: it types there,
and reads what the process showed.
"""

import os
import select
import subprocess
import sys
import termios
import time

import pytest

from processes import environment


class Terminal:
    """A pseudo-terminal, and Python running `arguments` at the far end.

    `patience` is how many seconds on the wall to wait for the process to
    show something, or to end.
    """

    def __init__(self, arguments, *, patience, **extra_environment):
        self.screen = b""
        self.patience = patience
        # Where the last text waited for ended: the next is looked for
        # after it.
        self.seen = 0
        self.controller, self.device = os.openpty()
        self.settings_at_the_start = self.settings()
        self.process = subprocess.Popen(
            [sys.executable, *arguments],
            stdin=self.device,
            stdout=self.device,
            stderr=subprocess.PIPE,
            env=environment(**extra_environment),
        )

    def settings(self):
        """The terminal's settings, as `termios` has them."""
        return termios.tcgetattr(self.device)

    def exit_status(self):
        """How the process ended, once it has, within `patience`."""
        try:
            return self.process.wait(timeout=self.patience)
        except subprocess.TimeoutExpired:
            pytest.fail(
                f"The process was still running {self.patience} s later. "
                f"The terminal showed:\n{self.shown()}"
            )

    def type(self, keys):
        os.write(self.controller, keys)

    def wait_for(self, text):
        """Read until the screen shows `text` after what was waited for last.

        What the process showed before it ended is read too.
        """
        deadline = time.monotonic() + self.patience
        while text not in self.screen[self.seen :]:
            ended = self.process.poll() is not None
            ready, _, _ = select.select(
                [self.controller], [], [], 0 if ended else 0.1
            )
            if ready:
                self.screen += os.read(self.controller, 4096)
            elif ended:
                pytest.fail(
                    f"The process ended before the terminal showed {text!r}:"
                    f"\n{self.process.stderr.read().decode()}"
                )
            elif time.monotonic() > deadline:
                pytest.fail(
                    f"The terminal never showed {text!r}. It showed:\n"
                    f"{self.shown()}"
                )
        self.seen = self.screen.index(text, self.seen) + len(text)

    def shown(self):
        """Everything the screen has shown, as text."""
        return self.screen.decode(errors="replace")

    def close(self):
        self.process.kill()
        self.process.wait()
        os.close(self.controller)
        os.close(self.device)
