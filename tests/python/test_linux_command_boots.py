"""🧦 `socpuppet linux` boots Linux, at a terminal and through a pipe.

Each test boots Linux once, which takes most of a minute or more.
"""

import re
import subprocess
import time

import pytest

import ssh_to_linux
from cable_area import needs_cable
from devicetree_compiler import needs_dtc
from linux_shell import linux_images
from processes import ended_or_killed, run_socpuppet, start_socpuppet
from pseudo_terminal import Terminal
from sockets import a_free_port
from socpuppet import linux

pytestmark = [needs_dtc, pytest.mark.long]


class TestWhenItIsGivenCommandsThroughAPipe:
    def test_linux_answers_them_and_poweroff_ends_it_saying_why(self, firmware):
        ran = run_socpuppet(
            "linux",
            input="uname -a\npoweroff\n",
            timeout=BOOTS_WITHIN,
            SOCPUPPET_FIRMWARE_DIR=str(linux_images(firmware)),
        )

        # 🐧 `uname -a` answers with the kernel's name and the host's,
        # which firmware/rootfs/etc/inittab sets.
        assert "Linux socpuppet" in ran.stdout
        assert "switched the host off" in ran.stderr


class TestWhenTheReaderOfItsPipedOutputHasGone:
    def test_it_ends_quietly_saying_so(self, firmware):
        # 🎓 `socpuppet linux | head -1`: head leaves with its line while
        # the boot is still scrolling by.
        with ended_or_killed(
            start_socpuppet(
                "linux", SOCPUPPET_FIRMWARE_DIR=str(linux_images(firmware))
            )
        ) as run:
            run.stdout.readline()
            run.stdout.close()

            ended = run.wait(timeout=BOOTS_WITHIN)

            said = run.stderr.read()
            assert ended == 0, said
            assert "reader has gone" in said
            # 🎓 The interpreter's own last flush of standard output, had it
            # failed, would have said so by this error's name. ⚠️ Not by
            # the order of the lines: QBox's CPU says its warnings from a
            # thread of its own, after socpuppet's last line or not.
            assert "BrokenPipeError" not in said
            assert "Traceback" not in said


@pytest.fixture
def linux_at_this_terminal(firmware):
    """`socpuppet linux` at a pseudo-terminal, as a person would run it."""
    terminal = Terminal(
        ["-m", "socpuppet", "linux"],
        patience=BOOTS_WITHIN,
        SOCPUPPET_FIRMWARE_DIR=str(linux_images(firmware)),
    )
    yield terminal
    terminal.close()


class TestWhenSomeoneRunsItAtATerminal:
    def test_the_boot_scrolls_by_and_then_the_shell_answers_what_is_typed(
        self, linux_at_this_terminal
    ):
        terminal = linux_at_this_terminal

        # OpenSBI's banner and the kernel's first words come on the UART,
        # and the prompt on the virtio console.
        terminal.wait_for(b"OpenSBI v")
        terminal.wait_for(b"Linux version")
        terminal.wait_for(PROMPT)
        terminal.type(b"uname -a\r")

        terminal.wait_for(b"Linux socpuppet")

    def test_ctrl_c_stops_what_the_shell_is_running(
        self, linux_at_this_terminal
    ):
        terminal = linux_at_this_terminal
        terminal.wait_for(PROMPT)
        terminal.type(b"echo spam; sleep 100\r")
        # What `echo` said, and not the keys' own echo: the shell is
        # running the line.
        terminal.wait_for(b"\r\nspam")

        terminal.type(b"\x03")

        terminal.wait_for(PROMPT, within=STOPS_WITHIN)

    def test_sleep_2_takes_at_least_2_seconds_on_the_wall(
        self, linux_at_this_terminal
    ):
        terminal = linux_at_this_terminal
        terminal.wait_for(PROMPT)
        terminal.type(b"sleep 2\r")
        terminal.wait_for(b"sleep 2")
        typed_at = time.monotonic()

        terminal.wait_for(PROMPT)

        assert time.monotonic() - typed_at >= 2


@pytest.fixture
def linux_at_this_terminal_with_ssh(firmware):
    """`socpuppet linux` at a pseudo-terminal, with a port for ssh.

    Gives the terminal and the port.
    """
    port = a_free_port()
    terminal = Terminal(
        ["-m", "socpuppet", "linux", "--ssh-port", str(port)],
        patience=BOOTS_WITHIN,
        SOCPUPPET_FIRMWARE_DIR=str(linux_images(firmware)),
    )
    yield terminal, port
    terminal.close()


@needs_cable
class TestWhenSomeoneSshesToLinuxWhileItRunsAtATerminal:
    def test_linux_answers_from_its_shell(
        self, linux_at_this_terminal_with_ssh
    ):
        terminal, port = linux_at_this_terminal_with_ssh
        terminal.wait_for(PROMPT)

        answer = ssh_answer(port, "uname -a")

        assert answer.startswith("Linux ")


def ssh_answer(port: int, command: str) -> str:
    """What `command` prints, run on Linux by this machine's ssh at `port`.

    dropbear may not be up yet at the prompt, so a try that fails is made
    again, until ANSWERS_WITHIN.
    """
    started = time.monotonic()
    while True:
        ran = subprocess.run(
            ssh_to_linux.ssh(port, command),
            capture_output=True,
            text=True,
            timeout=ANSWERS_WITHIN,
        )
        if ran.returncode == 0 or time.monotonic() - started > ANSWERS_WITHIN:
            assert ran.returncode == 0, ran.stderr
            return ran.stdout


PROMPT = re.compile(linux.PROMPT.pattern.encode())
#: Seconds on the wall for ssh to answer, once Linux has prompted: dropbear
#: makes its host key at the first connection, on the simulated CPU.
ANSWERS_WITHIN = 300
#: Seconds on the wall for Ctrl-C to bring the prompt back: far less than
#: the `sleep 100` it has to stop.
STOPS_WITHIN = 30
#: Seconds on the wall for the command to boot Linux and run a command or
#: two. Alone, the prompt comes in 75 to 100 s on the interpreter here;
#: three boots at once, beside the other long tests, have taken 230 s, and
#: four at once on CI's Intel Macs have gone past 600.
BOOTS_WITHIN = 900
