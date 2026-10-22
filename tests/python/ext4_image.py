"""Files read out of an ext4 filesystem image, by a borrowed reader.

🎓 ext4 is Linux's own filesystem, and the one its root is on here. The
reader is `ext4` from PyPI (github.com/Eeems/python-ext4, MIT), pure Python
and read-only: what this needs, which is to look at what Linux wrote.
"""

import io

import ext4


def file_in(filesystem, path):
    """The bytes of the file at `path` in `filesystem`, an ext4 image.

    ⚠️ The reader does not replay the journal, so what Linux wrote reads
    back once Linux has written it out: at an unmount, or a `poweroff`,
    which unmounts the root first.
    """
    # The reader peeks at its stream, which a buffered one can.
    volume = ext4.Volume(io.BufferedReader(io.BytesIO(filesystem)))
    return volume.inode_at(path).open().read()
