"""🧦 `socpuppet linux`: Linux on the host, at this terminal."""

from cast import FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4
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
