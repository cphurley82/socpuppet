"""🐧 Linux on the host the quick way, as the package boots it."""

import pytest

from cast import (
    FW_JUMP_BIN,
    INITRAMFS_CPIO,
    LINUX_BIN,
    MANAGER,
    ROOTFS_EXT4,
    SSD,
)
from socpuppet import ftl, gpt, linux

IMAGES = (FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4)
#: With its root on the drive, Linux boots with the initramfs, on a host
#: whose IO manager and SSD run their own firmware: by the part of
#: `firmware/build.py` that builds each.
ON_THE_DRIVE = {
    FW_JUMP_BIN: "opensbi linux",
    LINUX_BIN: "opensbi linux",
    ROOTFS_EXT4: "opensbi linux",
    INITRAMFS_CPIO: "opensbi linux",
    MANAGER: "zephyr",
    SSD: "zephyr",
}


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


class TestWhenAnImageForTheRootOnTheDriveIsMissing:
    @pytest.mark.parametrize("missing", ON_THE_DRIVE)
    def test_it_is_refused_with_its_path_and_the_command_that_builds_it(
        self, tmp_path, missing
    ):
        for image in set(ON_THE_DRIVE) - {missing}:
            (tmp_path / image).write_bytes(b"spam")

        with pytest.raises(FileNotFoundError) as refused:
            linux.host_with_linux(tmp_path, root="drive")

        assert str(tmp_path / missing) in str(refused.value)
        assert f"uv run firmware/build.py {ON_THE_DRIVE[missing]}" in str(
            refused.value
        )


@pytest.fixture
def a_host_with_its_root_on_the_drive(firmware):
    """The host `root="drive"` builds, from the images the build left.

    A missing image skips the test, with the command that builds it.
    """
    for image in ON_THE_DRIVE:
        firmware(image)
    return linux.host_with_linux(firmware(ROOTFS_EXT4).parent, root="drive")


@pytest.mark.platform
class TestWhenTheRootIsOnTheDrive:
    def test_the_ssds_nand_holds_the_root_filesystem_in_partition_1(
        self, a_host_with_its_root_on_the_drive, firmware
    ):
        rootfs = firmware(ROOTFS_EXT4).read_bytes()
        nand = a_host_with_its_root_on_the_drive.drive.ssd.nand

        drive = ftl.drive_image(nand.contents, nand.component)

        first, *_ = gpt.partitions(drive)
        assert first.kind == gpt.LINUX_FILESYSTEM
        assert first.data[: len(rootfs)] == rootfs

    def test_the_host_has_the_io_manager(
        self, a_host_with_its_root_on_the_drive
    ):
        assert a_host_with_its_root_on_the_drive.manager is not None
