"""FAT disk images for 🎭 the virtio disk, made and read with pyfatfs.

`make` gives a whole disk, with a FAT file system and files on it, ready
for `PlacedBlock.load` or for a partition; `files` reads them back, as a
test does with `PlacedBlock.contents` after a run.

pyfatfs works on a file, so each call goes through a temporary one.
"""

import tempfile
import warnings
from collections.abc import Mapping
from pathlib import Path

with warnings.catch_warnings():
    # PyFilesystem2, under pyfatfs, still imports pkg_resources, and
    # says so on import, twice over (docs/upstream.md).
    warnings.simplefilter("ignore", UserWarning)
    warnings.simplefilter("ignore", DeprecationWarning)
    from pyfatfs.PyFat import PyFat
    from pyfatfs.PyFatFS import PyFatFS

#: What a sector holds.
SECTOR = 512
#: The volume's label, which UEFI's `vol` prints.
LABEL = "PUPPET"
#: The smallest volume that is FAT16 and not FAT12, in sectors: 4.1 MB, by
#: the table in Microsoft's FAT specification (fatgen103).
FAT16_FROM = 8400


def make(files: Mapping[str, bytes], *, sectors: int) -> bytes:
    """A disk of `sectors` sectors with one FAT file system on it.

    It is FAT12 if it is smaller than `FAT16_FROM` sectors, and FAT16 if
    not. There is no partition table: the file system starts at sector 0,
    as on a floppy, which UEFI's FAT driver takes as readily as a
    partition. Each of `files` is at its path, a name in 8.3 form after
    the directories it is in, which are made.
    """
    with tempfile.TemporaryDirectory() as directory:
        disk = Path(directory) / "disk.img"
        disk.write_bytes(bytes(sectors * SECTOR))
        fat = PyFat()
        # A label of its own, of eight letters at most and no space: pyfatfs
        # writes the root directory's copy as an 8.3 name, which loses the
        # space of its own "NO NAME" and all past the eighth letter, and
        # fsck.fat finds the two copies differ (docs/upstream.md).
        fat.mkfs(
            str(disk),
            fat_type=(
                PyFat.FAT_TYPE_FAT12
                if sectors < FAT16_FROM
                else PyFat.FAT_TYPE_FAT16
            ),
            size=sectors * SECTOR,
            label=LABEL,
        )
        fat.close()
        with PyFatFS(str(disk)) as volume:
            for name, data in files.items():
                if "/" in name:
                    volume.makedirs(f"/{Path(name).parent}", recreate=True)
                volume.writebytes(f"/{name}", data)
        return disk.read_bytes()


def files(image: bytes) -> dict[str, bytes]:
    """The files of the FAT file system `image`, by their paths."""
    with tempfile.TemporaryDirectory() as directory:
        disk = Path(directory) / "disk.img"
        disk.write_bytes(image)
        with PyFatFS(str(disk), read_only=True) as volume:
            return {
                path.removeprefix("/"): volume.readbytes(path)
                for path in volume.walk.files()
            }
