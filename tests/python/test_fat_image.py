"""The FAT disk images the virtio disk is booted with.

🎓 FAT is the file system of floppies, memory cards and the EFI system
partition, and every UEFI reads it. `fat_image` makes one with pyfatfs and
reads files back out of one, so a test can hand firmware a disk and see
what it wrote there.
"""

import shutil
import subprocess

import pytest

import fat_image

FSCK = shutil.which("fsck.fat") or shutil.which("fsck.fat", path="/usr/sbin")


class TestWhenAnImageIsMadeWithTwoFiles:
    def test_both_are_read_back_out_of_it(self):
        files = {"SPAM.TXT": b"spam\r\n", "EGGS.TXT": b"eggs" * 300}

        image = fat_image.make(files, sectors=2048)

        assert fat_image.files(image) == files

    def test_it_fills_the_disk_it_was_made_for(self):
        image = fat_image.make({"SPAM.TXT": b"spam"}, sectors=2048)

        assert len(image) == 2048 * 512

    @pytest.mark.skipif(FSCK is None, reason="fsck.fat is not installed")
    def test_fsck_finds_nothing_to_mend(self, tmp_path):
        disk = tmp_path / "disk.img"
        disk.write_bytes(fat_image.make({"SPAM.TXT": b"spam"}, sectors=2048))

        checked = subprocess.run(
            [FSCK, "-n", str(disk)], capture_output=True, text=True
        )

        assert checked.returncode == 0, checked.stdout
