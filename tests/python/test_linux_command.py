"""🧦 `socpuppet linux`: Linux on the host, at this terminal."""

import pytest

from cast import FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4
from devicetree_compiler import needs_dtc
from linux_shell import linux_images
from processes import run_socpuppet


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
@pytest.mark.long
class TestWhenItIsGivenCommandsThroughAPipe:
    def test_linux_answers_them_and_poweroff_ends_it(self, firmware):
        ran = run_socpuppet(
            "linux",
            input="uname -a\npoweroff\n",
            timeout=BOOTS_WITHIN,
            SOCPUPPET_FIRMWARE_DIR=str(linux_images(firmware)),
        )

        # 🐧 `uname -a` answers with the kernel's name and the host's,
        # which firmware/rootfs/etc/inittab sets.
        assert "Linux socpuppet" in ran.stdout


#: Seconds on the wall for the command to boot Linux and run a command or
#: two: the prompt comes in 75 to 100 s on the interpreter here, CI's
#: machines take up to twice as long, and a minute is left for the rest.
BOOTS_WITHIN = 2 * 100 + 60
