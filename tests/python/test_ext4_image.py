"""Reading a file out of an ext4 filesystem, as Linux left it.

🎓 ext4 is the filesystem Linux's root is on here: Alpine's mini root, made
into an ext4 image by `firmware/build.py`. Python reads a file back out of
one with a borrowed reader, `ext4` from PyPI, behind `ext4_image`, so that
a test can check what Linux wrote to its drive. This holds the reader to
the images mkfs.ext4 makes, with whatever features it turns on.
"""

import pathlib

from cast import ROOTFS_EXT4
from ext4_image import file_in

REPO = pathlib.Path(__file__).resolve().parents[2]
#: The file of ours that `firmware/build.py` lays over Alpine's.
INITTAB = REPO / "firmware" / "rootfs" / "etc" / "inittab"


class TestWhenAFileIsReadOutOfTheRootFilesystem:
    def test_it_is_the_file_that_went_into_it(self, firmware):
        filesystem = firmware(ROOTFS_EXT4).read_bytes()

        assert file_in(filesystem, "/etc/inittab") == INITTAB.read_bytes()
