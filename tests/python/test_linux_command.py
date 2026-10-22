"""🧦 `socpuppet linux`: Linux on the host, at this terminal."""

import re
import time

import pytest

from cast import FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4
from devicetree_compiler import needs_dtc
from linux_shell import linux_images
from processes import run_socpuppet
from pseudo_terminal import Terminal
from socpuppet import _core, linux
from socpuppet.boards.virtio import SECTOR


class TestWhenAnImageIsNotBuilt:
    def test_it_fails_with_one_line_naming_it_and_how_to_build_it(
        self, tmp_path
    ):
        for image in (LINUX_BIN, ROOTFS_EXT4):
            (tmp_path / image).write_bytes(b"spam")

        ran = run_socpuppet(
            "linux", check=False, SOCPUPPET_FIRMWARE_DIR=str(tmp_path)
        )

        assert ran.returncode != 0
        said = ran.stderr.strip()
        assert "\n" not in said
        assert str(tmp_path / FW_JUMP_BIN) in said
        assert "uv run firmware/build.py opensbi linux" in said


@needs_dtc
@pytest.mark.skipif(_core.has_qbox, reason="this build has QBox's CPU")
class TestWhenItIsAskedForQboxsCpuInABuildWithoutIt:
    def test_it_fails_in_one_line_that_says_how_to_build_one(self, tmp_path):
        put_images_that_boot_nothing(tmp_path)

        ran = run_socpuppet(
            "linux",
            "--cpu",
            "qbox_cpu",
            check=False,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
        )

        assert ran.returncode != 0
        [line] = ran.stderr.strip().splitlines()
        assert "tools/build_qbox.py" in line

    def test_socpuppet_cpu_asks_for_it_as_the_option_does(self, tmp_path):
        put_images_that_boot_nothing(tmp_path)

        ran = run_socpuppet(
            "linux",
            check=False,
            SOCPUPPET_CPU="qbox_cpu",
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
        )

        assert ran.returncode != 0
        [line] = ran.stderr.strip().splitlines()
        assert "tools/build_qbox.py" in line


@needs_dtc
class TestWhenItStarts:
    def test_it_says_first_how_to_leave(self, tmp_path):
        put_images_that_boot_nothing(tmp_path)

        # Ctrl-], to leave at once.
        ran = run_socpuppet(
            "linux",
            input="\x1d",
            check=False,
            timeout=STOPS_WITHIN,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
        )

        first = ran.stderr.partition("\n")[0]
        assert "Ctrl-]" in first
        assert "Ctrl-]" not in ran.stdout


@needs_dtc
class TestWhenSomeoneLeaves:
    def test_it_says_so_on_a_line_of_its_own(self, tmp_path):
        put_images_that_boot_nothing(tmp_path)

        ran = run_socpuppet(
            "linux",
            input="\x1d",
            check=False,
            timeout=STOPS_WITHIN,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
        )

        # The line before it may be the end of Linux's prompt, on stdout.
        *_, before, last = ran.stderr.splitlines()
        assert before == ""
        assert "Left" in last


@needs_dtc
@pytest.mark.long
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
        assert "switched the host off" in ran.stderr.splitlines()[-1]


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


@needs_dtc
@pytest.mark.long
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


PROMPT = re.compile(linux.PROMPT.pattern.encode())
#: Seconds on the wall for Ctrl-C to bring the prompt back, far less than
#: the `sleep 100` it has to stop, or for Ctrl-] to end the command.
STOPS_WITHIN = 30
#: Seconds on the wall for the command to boot Linux and run a command or
#: two. Alone, the prompt comes in 75 to 100 s on the interpreter here;
#: three boots at once, beside the other long tests, have taken 230 s, and
#: CI's machines are slower still.
BOOTS_WITHIN = 600


def put_images_that_boot_nothing(directory):
    """Put the three images in `directory`, each a sector of spam.

    Enough for the command to describe the host and build it, and for
    nothing to boot.
    """
    for image in (FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4):
        (directory / image).write_bytes(b"spam" * (SECTOR // len(b"spam")))
