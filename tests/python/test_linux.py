"""🐧 Linux on the host the quick way, as the package boots it."""

import pytest

from cast import FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4
from socpuppet import linux

IMAGES = (FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4)


class TestWhenAnImageIsMissing:
    @pytest.mark.parametrize("missing", IMAGES)
    def test_it_is_refused_with_its_path_and_the_command_that_builds_it(
        self, tmp_path, missing
    ):
        for image in set(IMAGES) - {missing}:
            (tmp_path / image).write_bytes(b"spam")

        with pytest.raises(FileNotFoundError) as refused:
            linux.host_with_linux(tmp_path)

        assert str(tmp_path / missing) in str(refused.value)
        assert "uv run firmware/build.py opensbi linux" in str(refused.value)
