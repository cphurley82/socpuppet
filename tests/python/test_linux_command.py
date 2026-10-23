"""🧦 `socpuppet linux`: Linux on the host, at this terminal."""

import pytest

from cast import FW_JUMP_BIN, INITRAMFS_CPIO, LINUX_BIN, MANAGER, ROOTFS_EXT4
from devicetree_compiler import needs_dtc
from processes import run_socpuppet
from riscv_program import sleeps
from socpuppet import _core
from socpuppet.boards.virtio import SECTOR


class TestWhenAnImageIsNotBuilt:
    def test_it_fails_with_one_line_naming_it_and_how_to_build_it(
        self, tmp_path
    ):
        for image in (LINUX_BIN, ROOTFS_EXT4):
            (tmp_path / image).write_bytes(b"spam")

        ran = run_without_a_terminal(SOCPUPPET_FIRMWARE_DIR=str(tmp_path))

        assert ran.returncode != 0
        said = ran.stderr.strip()
        assert "\n" not in said
        assert str(tmp_path / FW_JUMP_BIN) in said
        assert "uv run firmware/build.py opensbi linux" in said


class TestWhenTheRootIsAskedForOnTheDrive:
    def test_an_image_it_needs_is_named_in_one_line_with_how_to_build_it(
        self, tmp_path
    ):
        # 🐧 The drive is the SSD, on a host whose IO manager and SSD run
        # their own firmware, which another part of the build makes.
        for image in (FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4, INITRAMFS_CPIO):
            (tmp_path / image).write_bytes(b"spam")

        ran = run_socpuppet(
            "linux",
            "--root",
            "drive",
            check=False,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
        )

        assert ran.returncode != 0
        said = ran.stderr.strip()
        assert "\n" not in said
        assert str(tmp_path / MANAGER) in said
        assert "uv run firmware/build.py zephyr" in said


@needs_dtc
@pytest.mark.skipif(_core.has_qbox, reason="this build has QBox's CPU")
class TestWhenItIsAskedForQboxsCpuInABuildWithoutIt:
    def test_it_fails_in_one_line_that_says_how_to_build_one(self, tmp_path):
        put_images_that_boot_nothing(tmp_path)

        ran = run_without_a_terminal(
            "--cpu", "qbox_cpu", SOCPUPPET_FIRMWARE_DIR=str(tmp_path)
        )

        assert ran.returncode != 0
        [line] = ran.stderr.strip().splitlines()
        assert "tools/build_qbox.py" in line

    def test_socpuppet_cpu_asks_for_it_as_the_option_does(self, tmp_path):
        put_images_that_boot_nothing(tmp_path)

        ran = run_without_a_terminal(
            SOCPUPPET_CPU="qbox_cpu", SOCPUPPET_FIRMWARE_DIR=str(tmp_path)
        )

        assert ran.returncode != 0
        [line] = ran.stderr.strip().splitlines()
        assert "tools/build_qbox.py" in line


@pytest.fixture(scope="module")
def left_at_once(tmp_path_factory):
    """The command, with images that boot nothing, and Ctrl-] typed at once.

    One run for the tests of what it says: each run builds a platform.
    """
    images = tmp_path_factory.mktemp("firmware")
    put_images_that_boot_nothing(images)
    return run_socpuppet(
        "linux",
        input="\x1d",
        check=False,
        timeout=LEAVES_WITHIN,
        SOCPUPPET_FIRMWARE_DIR=str(images),
    )


@needs_dtc
class TestWhenItStarts:
    def test_it_says_first_how_to_leave(self, left_at_once):
        ran = left_at_once

        first = ran.stderr.partition("\n")[0]
        assert "Ctrl-]" in first
        assert "Ctrl-]" not in ran.stdout


@needs_dtc
class TestWhenSomeoneLeaves:
    def test_it_says_so_on_a_line_of_its_own(self, left_at_once):
        ran = left_at_once

        # The line before it may be the end of Linux's prompt, on stdout.
        *_, before, last = ran.stderr.splitlines()
        assert before == ""
        assert "Left" in last


#: Seconds on the wall for Ctrl-] to end the command.
LEAVES_WITHIN = 30


def run_without_a_terminal(*arguments, **extra_environment):
    """Run `socpuppet linux` with `arguments`, expecting it to refuse.

    Its standard input is a pipe that has ended, not this process's
    terminal, and it is stopped after `LEAVES_WITHIN` seconds: a run that
    went on instead would otherwise hang the tests, with the terminal in
    raw mode.
    """
    return run_socpuppet(
        "linux",
        *arguments,
        input="",
        check=False,
        timeout=LEAVES_WITHIN,
        **extra_environment,
    )


def put_images_that_boot_nothing(directory):
    """Put the three images in `directory`, each a sector long.

    Enough for the command to describe the host and build it, and for
    nothing to boot: the kernel and the root are spam, and where OpenSBI
    would be is a program that sleeps. ⚠️ With spam there, QBox's CPU
    traps on every fetch, at an address nothing answers, and never yields
    the simulation (docs/models/qbox-cpu.md).
    """
    (directory / FW_JUMP_BIN).write_bytes(sleeps().ljust(SECTOR, b"\0"))
    for image in (LINUX_BIN, ROOTFS_EXT4):
        (directory / image).write_bytes(b"spam" * (SECTOR // len(b"spam")))
