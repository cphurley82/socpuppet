"""Disk images with a GUID partition table, as a server's disk is cut up.

🎓 A GUID partition table (GPT) is how a disk says where its partitions
are: a header at its start and a copy at its end, each pointing at a
table of the partitions, every part of it held to a CRC-32. UEFI reads
it, and so does Linux.

`make` gives a whole disk with a GUID partition table and the partitions
it is given, each starting on a mebibyte as partitioning tools put them,
ready for a drive: `PlacedBlock.load` for 🎭 the virtio disk, or
`socpuppet.ftl.nand_image` for the SSD. The disk's GUIDs are fixed, so
that two disks made of the same partitions are the same bytes.
`partitions` reads a disk's table back: a drive Python reads after a run,
to see what was written to it.
"""

from __future__ import annotations

import struct
import uuid
import zlib
from collections.abc import Sequence
from typing import NamedTuple

#: What a sector holds.
SECTOR = 512
#: The partition types used here, by the GUIDs the UEFI specification and
#: the Discoverable Partitions Specification give them.
EFI_SYSTEM = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")
LINUX_FILESYSTEM = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")
#: Where each partition starts: on a mebibyte, in sectors.
ALIGNMENT = 2048
#: The table: 128 entries of 128 bytes, 32 sectors, as every tool makes it.
ENTRIES = 128
ENTRY = struct.Struct("<16s16sQQQ72s")
TABLE_SECTORS = ENTRIES * ENTRY.size // SECTOR
#: The header's fields, up to its own size; the rest of its sector is zeros.
HEADER = struct.Struct("<8sIIIIQQQQ16sQIII")
REVISION = 0x0001_0000
#: The protective MBR's one entry: a partition of type 0xEE over the disk.
PROTECTIVE = 0xEE
#: The disk's GUID, and the namespace each partition's own is made in.
DISK_GUID = uuid.uuid5(uuid.NAMESPACE_URL, "https://socpuppet/disk")


class Partition(NamedTuple):
    """A partition: its type, its name, and what it holds."""

    kind: uuid.UUID
    name: str
    data: bytes


def size_of(partitions: Sequence[Partition]) -> int:
    """How many sectors `make` gives `partitions` when it is not told.

    The partitions, each from a mebibyte, then the table's copy and the
    backup header after the last mebibyte they reach.
    """
    placed = _placed(partitions)
    last = placed[-1][2] + 1 if placed else 0
    return _to_a_mebibyte(max(last, ALIGNMENT)) + TABLE_SECTORS + 1


def _placed(
    partitions: Sequence[Partition],
) -> list[tuple[Partition, int, int]]:
    """Each partition, with its first and last sectors, each from a MiB."""
    placed = []
    lba = ALIGNMENT
    for partition in partitions:
        length = -(-len(partition.data) // SECTOR)
        placed.append((partition, lba, lba + length - 1))
        lba = _to_a_mebibyte(lba + length)
    return placed


def _to_a_mebibyte(lba: int) -> int:
    """`lba`, or the first sector on a mebibyte after it."""
    return -(-lba // ALIGNMENT) * ALIGNMENT


def make(
    partitions: Sequence[Partition], *, sectors: int | None = None
) -> bytes:
    """A disk with a GUID partition table and `partitions`, in order.

    Each partition is as big as its data, rounded up to a sector, and
    starts on a mebibyte; the disk ends with the table's copy and a
    backup header. The disk is `sectors` big, or without it big enough,
    to the next mebibyte. 💡 Give the drive's size when the disk is for a
    drive: the table's copy and the backup header belong in the drive's
    last sectors, where tools look for them. Raises ValueError if
    `sectors` cannot hold the partitions and the table's two copies.
    """
    placed = _placed(partitions)
    # After the last partition: the table's copy, then the backup header.
    end = placed[-1][2] + 1 if placed else 2 + TABLE_SECTORS
    needed = end + TABLE_SECTORS + 1
    total = size_of(partitions) if sectors is None else sectors
    if total < needed:
        raise ValueError(
            f"A disk of {total} sectors cannot hold these partitions and the "
            f"partition table's two copies, which need {needed}. Give it at "
            "least that many sectors, or smaller partitions."
        )
    disk = bytearray(total * SECTOR)

    disk[446:462] = struct.pack(
        "<B3sB3sII",
        0,
        b"\x00\x02\x00",
        PROTECTIVE,
        b"\xff\xff\xff",
        1,
        min(total - 1, 0xFFFF_FFFF),
    )
    disk[510:512] = b"\x55\xaa"

    table = bytearray(TABLE_SECTORS * SECTOR)
    for index, (partition, first, last) in enumerate(placed):
        ENTRY.pack_into(
            table,
            index * ENTRY.size,
            partition.kind.bytes_le,
            uuid.uuid5(DISK_GUID, str(index)).bytes_le,
            first,
            last,
            0,
            partition.name.encode("utf-16-le"),
        )
        disk[first * SECTOR : first * SECTOR + len(partition.data)] = (
            partition.data
        )

    backup = total - 1
    backup_table = backup - TABLE_SECTORS
    first_usable = 2 + TABLE_SECTORS
    for at, other, table_at in ((1, backup, 2), (backup, 1, backup_table)):
        disk[table_at * SECTOR : (table_at + TABLE_SECTORS) * SECTOR] = table
        fields = [
            b"EFI PART",
            REVISION,
            HEADER.size,
            0,
            0,
            at,
            other,
            first_usable,
            backup_table - 1,
            DISK_GUID.bytes_le,
            table_at,
            ENTRIES,
            ENTRY.size,
            zlib.crc32(table),
        ]
        fields[3] = zlib.crc32(HEADER.pack(*fields))
        HEADER.pack_into(disk, at * SECTOR, *fields)
    return bytes(disk)


def partitions(disk: bytes) -> list[Partition]:
    """The partitions `disk`'s GUID partition table says it has, in order.

    Each one's data is every sector the table gives it, so a partition
    made of data that does not fill its last sector reads back with zeros
    after it. A disk whose sector 1 is not a GPT header has none.
    """
    fields = HEADER.unpack_from(disk, SECTOR)
    signature, entries_at, count = fields[0], fields[10], fields[11]
    if signature != b"EFI PART":
        return []
    found = []
    for index in range(count):
        kind, _, first, last, _, name = ENTRY.unpack_from(
            disk, entries_at * SECTOR + index * ENTRY.size
        )
        if kind != bytes(16):
            found.append(
                Partition(
                    uuid.UUID(bytes_le=kind),
                    name.decode("utf-16-le").rstrip("\0"),
                    disk[first * SECTOR : (last + 1) * SECTOR],
                )
            )
    return found
