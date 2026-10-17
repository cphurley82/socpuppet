"""🧵 Python serving a directory over FUSE, as virtio-fs carries it.

🎓 FUSE is Linux's protocol for a file system served by a program instead
of a driver: each request is a header (what to do, to which node) and a
body, and each answer a header (how it went) and a body. virtio-fs carries
the same requests from a guest's driver to the host. These tests hand
`socpuppet.fuse.Directory` requests built byte by byte, as Zephyr's and
EDK2's clients build them, with no simulator, and read its answers the
same way.
"""

import errno
import os
import struct

import pytest

from socpuppet import fuse

ROOT = 1
# The Linux numbers a guest reads in an answer's error, whatever the host
# Python runs on calls them.
ENOENT = 2
EEXIST = 17
ENOTEMPTY = 39
ENOSYS = 38
EACCES = 13

IN_HEADER = struct.Struct("<IIQQIIIHH")
OUT_HEADER = struct.Struct("<IiQ")
ATTR = struct.Struct("<QQQQQQIIIIIIIIII")
ENTRY_OUT = struct.Struct("<QQQQII")
OPEN_OUT = struct.Struct("<QII")
READ_IN = struct.Struct("<QQIIQII")
DIRENT = struct.Struct("<QQII")


def ask(served, opcode, body=b"", *, node=ROOT, unique=7):
    """Hands `served` one request, and gives the answer's error and body.

    Checks the answer's header on the way: its length is the answer's,
    and it carries the request's `unique`.
    """
    request = (
        IN_HEADER.pack(
            IN_HEADER.size + len(body), opcode, unique, node, 0, 0, 0, 0, 0
        )
        + body
    )
    answer = served(request)
    length, error, echoed = OUT_HEADER.unpack_from(answer)
    assert (length, echoed) == (len(answer), unique)
    return -error, answer[OUT_HEADER.size :]


def name(text):
    return text.encode() + b"\0"


def entry(body):
    """The node and the attributes an entry answer gives."""
    nodeid, *_ = ENTRY_OUT.unpack_from(body)
    return nodeid, ATTR.unpack_from(body, ENTRY_OUT.size)


def size_of(attr):
    return attr[1]


def mode_of(attr):
    return attr[9]


def look_up(served, text, *, under=ROOT):
    error, body = ask(served, fuse.LOOKUP, name(text), node=under)
    assert error == 0, os.strerror(error)
    return entry(body)[0]


def open_it(served, node, *, directory=False):
    opcode = fuse.OPENDIR if directory else fuse.OPEN
    error, body = ask(
        served, opcode, struct.pack("<II", os.O_RDWR, 0), node=node
    )
    assert error == 0
    return OPEN_OUT.unpack(body)[0]


def read_in(fh, offset, size):
    return READ_IN.pack(fh, offset, size, 0, 0, 0, 0)


def dirents(body, *, plus=False):
    """The names in a READDIR answer, or a READDIRPLUS one, in order."""
    names, at = [], 0
    while at < len(body):
        if plus:
            at += ENTRY_OUT.size + ATTR.size
        _, _, length, _ = DIRENT.unpack_from(body, at)
        start = at + DIRENT.size
        names.append(body[start : start + length].decode())
        at = start + (length + 7) // 8 * 8
    return names


@pytest.fixture
def served(tmp_path):
    (tmp_path / "spam.txt").write_bytes(b"spam, spam, spam\n")
    (tmp_path / "eggs").mkdir()
    (tmp_path / "eggs" / "bacon.txt").write_bytes(b"bacon")
    return fuse.Directory(tmp_path)


class TestWhenTheClientSaysHello:
    def test_zephyrs_long_init_gets_version_7_31_and_no_flags_it_did_not_ask(
        self, served
    ):
        error, body = ask(
            served, fuse.INIT, struct.pack("<IIII", 7, 31, 0, 0) + bytes(48)
        )

        major, minor, _, flags = struct.unpack_from("<IIII", body)
        assert (error, major, minor, flags, len(body)) == (0, 7, 31, 0, 64)

    def test_edk2s_short_init_asking_for_readdirplus_gets_it_and_room_to_write(
        self, served
    ):
        error, body = ask(
            served,
            fuse.INIT,
            struct.pack("<IIII", 7, 31, 0, fuse.DO_READDIRPLUS),
        )

        flags = struct.unpack_from("<I", body, 12)[0]
        max_write = struct.unpack_from("<I", body, 20)[0]
        assert error == 0
        assert flags & fuse.DO_READDIRPLUS
        assert max_write >= 4096


class TestWhenTheClientLooksANameUp:
    def test_a_file_gets_a_node_of_its_own_with_its_size_and_kind(self, served):
        error, body = ask(served, fuse.LOOKUP, name("spam.txt"))

        node, attr = entry(body)
        assert (error, size_of(attr), mode_of(attr) & 0o170000) == (
            0,
            17,
            0o100000,
        )
        assert node not in (0, ROOT)

    def test_the_same_name_twice_gets_the_same_node(self, served):
        assert look_up(served, "spam.txt") == look_up(served, "spam.txt")

    def test_a_name_that_is_not_there_is_enoent(self, served):
        assert ask(served, fuse.LOOKUP, name("ham"))[0] == ENOENT

    def test_dot_dot_at_the_top_is_the_top_and_goes_no_further(self, served):
        assert look_up(served, "..") == ROOT

    def test_a_link_that_leads_out_of_the_directory_is_refused(
        self, served, tmp_path
    ):
        (tmp_path / "out").symlink_to("/")

        assert ask(served, fuse.LOOKUP, name("out"))[0] == EACCES


class TestWhenTheClientAsksForANodesAttributes:
    def test_the_top_is_a_directory(self, served):
        error, body = ask(served, fuse.GETATTR, struct.pack("<IIQ", 0, 0, 0))

        attr = ATTR.unpack_from(body, 16)
        assert (error, mode_of(attr) & 0o170000, len(body)) == (
            0,
            0o040000,
            104,
        )


class TestWhenTheClientReadsAFile:
    def test_it_gets_the_bytes_from_the_offset_on(self, served):
        node = look_up(served, "spam.txt")
        fh = open_it(served, node)

        error, body = ask(served, fuse.READ, read_in(fh, 6, 4), node=node)

        assert (error, body) == (0, b"spam")

    def test_reading_past_the_end_gets_nothing(self, served):
        node = look_up(served, "spam.txt")
        fh = open_it(served, node)

        assert ask(served, fuse.READ, read_in(fh, 100, 4), node=node) == (
            0,
            b"",
        )


class TestWhenTheClientWritesAFile:
    def test_the_bytes_land_in_the_file_at_the_offset(self, served, tmp_path):
        node = look_up(served, "spam.txt")
        fh = open_it(served, node)

        error, body = ask(
            served,
            fuse.WRITE,
            struct.pack("<QQIIQII", fh, 0, 4, 0, 0, 0, 0) + b"SPAM",
            node=node,
        )

        assert (error, struct.unpack("<II", body)[0]) == (0, 4)
        assert (tmp_path / "spam.txt").read_bytes() == b"SPAM, spam, spam\n"


class TestWhenTheClientCreatesAFile:
    def test_it_is_made_and_opened_and_the_answer_has_both(
        self, served, tmp_path
    ):
        error, body = ask(
            served,
            fuse.CREATE,
            struct.pack("<IIII", os.O_RDWR | os.O_CREAT, 0o644, 0o022, 0)
            + name("ham.txt"),
        )

        assert (error, len(body)) == (0, ENTRY_OUT.size + ATTR.size + 16)
        assert (tmp_path / "ham.txt").exists()

    def test_a_name_that_is_taken_with_o_excl_is_eexist(self, served):
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        assert (
            ask(
                served,
                fuse.CREATE,
                struct.pack("<IIII", flags, 0o644, 0, 0) + name("spam.txt"),
            )[0]
            == EEXIST
        )


class TestWhenTheClientChangesAFilesAttributes:
    def test_a_new_size_truncates_it(self, served, tmp_path):
        node = look_up(served, "spam.txt")
        setattr_in = struct.pack(
            "<IIQQQQQQIIIIIIII", fuse.FATTR_SIZE, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0,
        )  # fmt: skip

        error, body = ask(served, fuse.SETATTR, setattr_in, node=node)

        assert (error, size_of(ATTR.unpack_from(body, 16))) == (0, 4)
        assert (tmp_path / "spam.txt").read_bytes() == b"spam"


class TestWhenTheClientListsADirectory:
    def test_readdir_gives_dot_dot_dot_and_the_names_in_order(self, served):
        fh = open_it(served, ROOT, directory=True)

        error, body = ask(served, fuse.READDIR, read_in(fh, 0, 4096))

        assert (error, dirents(body)) == (0, [".", "..", "eggs", "spam.txt"])

    def test_readdir_from_an_offset_carries_on_from_there(self, served):
        fh = open_it(served, ROOT, directory=True)

        _, body = ask(served, fuse.READDIR, read_in(fh, 3, 4096))

        assert dirents(body) == ["spam.txt"]

    def test_readdir_gives_no_more_than_fits_in_the_size_asked(self, served):
        fh = open_it(served, ROOT, directory=True)

        # Each of "." and ".." is a 24-byte header and its name padded to
        # eight bytes: 64 bytes for the two, and one short of the third.
        _, body = ask(served, fuse.READDIR, read_in(fh, 0, 64 + 31))

        assert dirents(body) == [".", ".."]

    def test_readdirplus_gives_each_names_entry_with_it(self, served):
        fh = open_it(served, ROOT, directory=True)

        error, body = ask(served, fuse.READDIRPLUS, read_in(fh, 2, 4096))

        assert (error, dirents(body, plus=True)) == (0, ["eggs", "spam.txt"])
        node, _ = entry(body)
        assert node == look_up(served, "eggs")


class TestWhenTheClientMakesAndRemovesDirectories:
    def test_mkdir_makes_one_and_gives_its_entry(self, served, tmp_path):
        error, body = ask(
            served, fuse.MKDIR, struct.pack("<II", 0o755, 0o022) + name("ham")
        )

        assert error == 0
        assert mode_of(entry(body)[1]) & 0o170000 == 0o040000
        assert (tmp_path / "ham").is_dir()

    def test_rmdir_of_one_with_something_in_it_is_enotempty(self, served):
        assert ask(served, fuse.RMDIR, name("eggs"))[0] == ENOTEMPTY

    def test_unlink_removes_a_file(self, served, tmp_path):
        assert ask(served, fuse.UNLINK, name("spam.txt"))[0] == 0
        assert not (tmp_path / "spam.txt").exists()


class TestWhenTheClientRenames:
    def test_rename_moves_a_file_into_another_directory(self, served, tmp_path):
        eggs = look_up(served, "eggs")

        error, _ = ask(
            served,
            fuse.RENAME,
            struct.pack("<Q", eggs) + name("spam.txt") + name("ham.txt"),
        )

        assert error == 0
        assert (tmp_path / "eggs" / "ham.txt").read_bytes().startswith(b"spam")

    def test_rename2_as_edk2_sends_it_does_the_same(self, served, tmp_path):
        error, _ = ask(
            served,
            fuse.RENAME2,
            struct.pack("<QII", ROOT, 0, 0)
            + name("spam.txt")
            + name("ham.txt"),
        )

        assert error == 0
        assert (tmp_path / "ham.txt").exists()


class TestWhenTheClientSeeks:
    def test_seek_end_gives_the_files_size(self, served):
        node = look_up(served, "spam.txt")
        fh = open_it(served, node)

        error, body = ask(
            served, fuse.LSEEK, struct.pack("<QQII", fh, 0, os.SEEK_END, 0),
            node=node,
        )  # fmt: skip

        assert (error, struct.unpack("<Q", body)[0]) == (0, 17)


class TestWhenTheClientAsksAboutTheFileSystem:
    def test_statfs_gives_a_block_size_and_how_long_a_name_may_be(self, served):
        error, body = ask(served, fuse.STATFS)

        blocks, *_, bsize, namelen, _, _ = struct.unpack_from(
            "<QQQQQIIII", body
        )
        assert (error, len(body)) == (0, 80)
        assert bsize > 0
        assert namelen == 255
        assert blocks > 0


@pytest.mark.parametrize(
    ("opcode", "body"),
    [
        (fuse.RELEASE, struct.pack("<QIIQ", 0, 0, 0, 0)),
        (fuse.RELEASEDIR, struct.pack("<QIIQ", 0, 0, 0, 0)),
        (fuse.FLUSH, struct.pack("<QIIQ", 0, 0, 0, 0)),
        (fuse.FSYNC, struct.pack("<QII", 0, 0, 0)),
        (fuse.FSYNCDIR, struct.pack("<QII", 0, 0, 0)),
        (fuse.DESTROY, b""),
    ],
)
class TestWhenTheClientLetsGoOrAsksForWhatIsWrittenToBeKept:
    def test_the_answer_is_a_header_that_says_it_went_well(
        self, served, opcode, body
    ):
        assert ask(served, opcode, body) == (0, b"")


class TestWhenTheClientForgetsANode:
    def test_there_is_no_answer_at_all(self, served):
        request = IN_HEADER.pack(48, fuse.FORGET, 7, 2, 0, 0, 0, 0, 0)

        assert served(request + struct.pack("<Q", 1)) == b""


class TestWhenTheClientAsksForSomethingTheDirectoryDoesNotDo:
    def test_it_is_enosys(self, served):
        getxattr = 22
        assert ask(served, getxattr, b"")[0] == ENOSYS


class TestWhenTheHostsErrorNumbersAreNotLinuxs:
    def test_an_answer_carries_linuxs_number_for_the_error(self):
        assert fuse.linux_errno(OSError(errno.ENOTEMPTY, "")) == ENOTEMPTY
