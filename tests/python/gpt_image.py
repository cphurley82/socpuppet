"""GPT disk images for 🎭 the virtio disk, as a server's disk is cut up.

`make` gives a whole disk with a GUID partition table and the partitions
it is given, each starting on a mebibyte as partitioning tools put them,
ready for `PlacedBlock.load`. The disk's GUIDs are fixed, so that two
disks made of the same partitions are the same bytes.
"""

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
    """A partition to be made: its type, its name, and what it holds."""

    kind: uuid.UUID
    name: str
    data: bytes


def make(partitions: Sequence[Partition]) -> bytes:
    """A disk with a GUID partition table and `partitions`, in order.

    Each partition is as big as its data, rounded up to a sector, and
    starts on a mebibyte; the disk ends with the table's copy and a
    backup header after the last.
    """
    placed = []
    lba = ALIGNMENT
    for partition in partitions:
        sectors = -(-len(partition.data) // SECTOR)
        placed.append((partition, lba, lba + sectors - 1))
        lba = -(-(lba + sectors) // ALIGNMENT) * ALIGNMENT
    total = lba + TABLE_SECTORS + 1
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
