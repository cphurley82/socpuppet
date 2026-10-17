"""FAT disk images for 🎭 the virtio disk, made and read with pyfatfs.

`make` gives a whole disk, with a FAT12 file system and files in its root
directory, ready for `PlacedBlock.load`; `files` reads the root directory
of one back, as a test does with `PlacedBlock.contents` after a run.

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


def make(files: Mapping[str, bytes], *, sectors: int) -> bytes:
    """A disk of `sectors` sectors with one FAT12 file system on it.

    There is no partition table: the file system starts at sector 0, as
    on a floppy, which UEFI's FAT driver takes as readily as a partition.
    Each of `files` is in the root directory, by its 8.3 name.
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
            fat_type=PyFat.FAT_TYPE_FAT12,
            size=sectors * SECTOR,
            label=LABEL,
        )
        fat.close()
        with PyFatFS(str(disk)) as volume:
            for name, data in files.items():
                volume.writebytes(f"/{name}", data)
        return disk.read_bytes()


def files(image: bytes) -> dict[str, bytes]:
    """The files in the root directory of the FAT file system `image`."""
    with tempfile.TemporaryDirectory() as directory:
        disk = Path(directory) / "disk.img"
        disk.write_bytes(image)
        with PyFatFS(str(disk), read_only=True) as volume:
            return {
                name: volume.readbytes(f"/{name}")
                for name in volume.listdir("/")
                if volume.isfile(f"/{name}")
            }
