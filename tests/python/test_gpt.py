"""The partitioned disk images a server's firmware boots from.

🎓 A GUID partition table (GPT) is how UEFI expects a disk to be cut up:
a protective MBR in sector 0, so that an older tool sees the disk as in
use, a header in sector 1 that says where the table of partitions is,
the table, and a copy of header and table at the end of the disk. Each
part is held to a CRC-32. `socpuppet.gpt` makes one with an EFI system
partition and a Linux root, so that UEFI can find the kernel on the one
and the kernel its root on the other.
"""

import re
import shutil
import struct
import subprocess
import uuid
import zlib

import pytest

from socpuppet import gpt

SECTOR = 512
SGDISK = shutil.which("sgdisk") or shutil.which("sgdisk", path="/usr/sbin")
#: What the two partitions hold: a sector and a half of spam, three of eggs.
SPAM = b"spam" * 192
EGGS = b"eggs" * 384


@pytest.fixture
def disk():
    return gpt.make(
        [
            gpt.Partition(gpt.EFI_SYSTEM, "spam", SPAM),
            gpt.Partition(gpt.LINUX_FILESYSTEM, "eggs", EGGS),
        ]
    )


def header_at(disk, lba):
    """The GPT header in sector `lba`, as its fields by name."""
    fields = struct.unpack_from("<8sIIIIQQQQ16sQIII", disk, lba * SECTOR)
    names = [
        "signature",
        "revision",
        "size",
        "crc",
        "reserved",
        "current",
        "backup",
        "first_usable",
        "last_usable",
        "disk_guid",
        "entries_at",
        "entries",
        "entry_size",
        "entries_crc",
    ]
    return dict(zip(names, fields, strict=True))


def entries_at(disk, header):
    start = header["entries_at"] * SECTOR
    return disk[start : start + header["entries"] * header["entry_size"]]


class TestWhenADiskIsMadeWithTwoPartitions:
    def test_sector_0_is_a_protective_mbr_over_the_whole_disk(self, disk):
        status, kind, first, count = struct.unpack_from("<B3xB3xII", disk, 446)

        assert disk[510:512] == b"\x55\xaa"
        assert (status, kind, first) == (0, 0xEE, 1)
        assert count == len(disk) // SECTOR - 1

    def test_the_header_and_its_table_hold_to_their_crcs(self, disk):
        header = header_at(disk, 1)
        raw = bytearray(disk[SECTOR : SECTOR + header["size"]])
        raw[16:20] = bytes(4)

        assert header["signature"] == b"EFI PART"
        assert header["crc"] == zlib.crc32(raw)
        assert header["entries_crc"] == zlib.crc32(entries_at(disk, header))

    def test_the_partitions_hold_what_was_given_where_the_table_says(
        self, disk
    ):
        table = entries_at(disk, header_at(disk, 1))
        found = []
        for index in range(2):
            kind, _, first, last, _ = struct.unpack_from(
                "<16s16sQQQ", table, index * 128
            )
            name = table[index * 128 + 56 : index * 128 + 128]
            found.append(
                (
                    uuid.UUID(bytes_le=kind),
                    name.decode("utf-16-le").rstrip("\0"),
                    disk[first * SECTOR : (last + 1) * SECTOR],
                )
            )

        assert found[0][:2] == (gpt.EFI_SYSTEM, "spam")
        assert found[0][2].rstrip(b"\0") == SPAM
        assert found[1][:2] == (gpt.LINUX_FILESYSTEM, "eggs")
        assert found[1][2].rstrip(b"\0") == EGGS

    def test_the_last_sector_is_a_backup_header_pointing_back_at_the_first(
        self, disk
    ):
        last = len(disk) // SECTOR - 1
        primary, backup = header_at(disk, 1), header_at(disk, last)

        assert (backup["current"], backup["backup"]) == (last, 1)
        assert (primary["current"], primary["backup"]) == (1, last)
        assert entries_at(disk, backup) == entries_at(disk, primary)

    @pytest.mark.skipif(SGDISK is None, reason="sgdisk is not installed")
    def test_sgdisk_lists_both_partitions_and_finds_no_problems(
        self, disk, tmp_path
    ):
        # ⚠️ sgdisk finds no problems on a disk of zeros either, since it
        # makes a table in memory for one that has none: so it lists them.
        image = tmp_path / "disk.img"
        image.write_bytes(disk)

        listed = subprocess.run(
            [SGDISK, "--print", "--verify", str(image)],
            capture_output=True,
            text=True,
        )

        assert re.search(r"^\s+1\s.*EF00\s+spam$", listed.stdout, re.M)
        assert re.search(r"^\s+2\s.*8300\s+eggs$", listed.stdout, re.M)
        assert "No problems found" in listed.stdout, listed.stdout


class TestWhenADiskIsReadBack:
    def test_its_partitions_are_what_it_was_made_with_in_whole_sectors(
        self, disk
    ):
        found = gpt.partitions(disk)

        assert [(each.kind, each.name) for each in found] == [
            (gpt.EFI_SYSTEM, "spam"),
            (gpt.LINUX_FILESYSTEM, "eggs"),
        ]
        assert found[0].data == SPAM.ljust(2 * SECTOR, b"\0")
        assert found[1].data == EGGS

    def test_a_disk_with_no_table_has_no_partitions(self):
        assert gpt.partitions(bytes(64 * SECTOR)) == []

    def test_a_disk_too_short_for_a_header_has_no_partitions(self):
        # A drive read back before anything was on it may be shorter
        # than the two sectors a header needs.
        assert gpt.partitions(bytes(SECTOR)) == []


#: A disk far bigger than its partitions: 8 MiB.
DRIVE_SECTORS = 8 * 2048


@pytest.fixture
def disk_of_a_drive():
    """The two partitions on a disk as big as `DRIVE_SECTORS`."""
    return gpt.make(
        [
            gpt.Partition(gpt.EFI_SYSTEM, "spam", SPAM),
            gpt.Partition(gpt.LINUX_FILESYSTEM, "eggs", EGGS),
        ],
        sectors=DRIVE_SECTORS,
    )


class TestWhenADiskIsMadeAsBigAsADrive:
    """🎓 A partition table's copy is at the disk's end, so a disk image
    for a drive is as big as the drive, or the copy is not where the
    drive's end is, and a tool that looks there finds none."""

    def test_it_is_that_many_sectors(self, disk_of_a_drive):
        assert len(disk_of_a_drive) == DRIVE_SECTORS * SECTOR

    def test_its_backup_header_is_in_the_drives_last_sector(
        self, disk_of_a_drive
    ):
        last = DRIVE_SECTORS - 1

        assert header_at(disk_of_a_drive, 1)["backup"] == last
        assert header_at(disk_of_a_drive, last)["signature"] == b"EFI PART"

    def test_a_disk_too_small_for_its_partitions_is_refused(self):
        # Smaller than a partition table and its copy alone.
        with pytest.raises(ValueError, match=r"64 sectors.*need"):
            gpt.make(
                [gpt.Partition(gpt.LINUX_FILESYSTEM, "eggs", EGGS)],
                sectors=64,
            )

    @pytest.mark.skipif(SGDISK is None, reason="sgdisk is not installed")
    def test_sgdisk_lists_its_partitions_and_finds_no_problems(
        self, disk_of_a_drive, tmp_path
    ):
        # ⚠️ Listed, as above, so that it is the disk's own table sgdisk
        # read and not one it made in memory.
        image = tmp_path / "disk.img"
        image.write_bytes(disk_of_a_drive)

        verified = subprocess.run(
            [SGDISK, "--print", "--verify", str(image)],
            capture_output=True,
            text=True,
        )

        assert re.search(r"^\s+2\s.*8300\s+eggs$", verified.stdout, re.M)
        assert "No problems found" in verified.stdout, verified.stdout
