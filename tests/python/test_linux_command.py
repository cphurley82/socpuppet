"""🧦 `socpuppet linux`: Linux on the host, at this terminal."""

import pytest

from cast import FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4
from devicetree_compiler import needs_dtc
from processes import run_socpuppet
from socpuppet import _core
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
            timeout=LEAVES_WITHIN,
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
            timeout=LEAVES_WITHIN,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
        )

        # The line before it may be the end of Linux's prompt, on stdout.
        *_, before, last = ran.stderr.splitlines()
        assert before == ""
        assert "Left" in last


#: Seconds on the wall for Ctrl-] to end the command.
LEAVES_WITHIN = 30


def put_images_that_boot_nothing(directory):
    """Put the three images in `directory`, each a sector of spam.

    Enough for the command to describe the host and build it, and for
    nothing to boot.
    """
    for image in (FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4):
        (directory / image).write_bytes(b"spam" * (SECTOR // len(b"spam")))
