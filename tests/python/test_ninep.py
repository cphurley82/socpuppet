"""🧵 Python serving a directory over 9P2000.L, as Linux's client asks.

🎓 9P2000.L is the dialect of Plan 9's file protocol that Linux's 9p
client speaks over virtio (`socpuppet.ninep`). These tests hand
`socpuppet.ninep.Directory` T-messages built byte by byte, as the kernel
builds them, with no simulator, and read its R-messages the same way.
"""

import os
import struct

import pytest

from socpuppet import ninep

#: Linux's numbers a client reads in an Rlerror, whatever this machine
#: calls them.
ENOENT = 2
EBADF = 9
EACCES = 13
EEXIST = 17
EINVAL = 22
EOPNOTSUPP = 95
ROOT_FID = 1
TAG = 0x1234


def t(kind, *fields):
    """A T-message of `kind` with `fields`: ints as (value, width), bytes as
    strings."""
    body = b"".join(
        struct.pack("<H", len(each)) + each
        if isinstance(each, bytes)
        else each[0].to_bytes(each[1], "little")
        for each in fields
    )
    return struct.pack("<IBH", 7 + len(body), kind, TAG) + body


class Answer:
    """An R-message, taken apart: its kind, its tag, and a body to read."""

    def __init__(self, message):
        self.size, self.kind, self.tag = struct.unpack_from("<IBH", message)
        assert self.size == len(message)
        self.body = message[7:]
        self.at = 0

    def number(self, width):
        value = int.from_bytes(self.body[self.at : self.at + width], "little")
        self.at += width
        return value

    def string(self):
        return self.bytes(self.number(2))

    def bytes(self, count):
        data = self.body[self.at : self.at + count]
        self.at += count
        return data

    def qid(self):
        kind = self.number(1)
        self.number(4)  # The version, which changes when the file does.
        return kind, self.number(8)

    @property
    def error(self):
        """Linux's errno, if this is an Rlerror, else None."""
        return self.number(4) if self.kind == ninep.RLERROR else None


@pytest.fixture
def share(tmp_path):
    (tmp_path / "spam.txt").write_bytes(b"spam spam spam\n")
    (tmp_path / "eggs").mkdir()
    (tmp_path / "eggs" / "ham.txt").write_bytes(b"ham")
    return tmp_path


@pytest.fixture
def served(share):
    """The share served, with the client attached to its root as ROOT_FID."""
    directory = ninep.Directory(share)
    answer = Answer(directory(t(ninep.TVERSION, (65536, 4), b"9P2000.L")))
    assert answer.kind == ninep.TVERSION + 1
    attached = Answer(
        directory(
            t(
                ninep.TATTACH,
                (ROOT_FID, 4),
                (ninep.NO_FID, 4),
                b"nobody",
                b"",
                (0, 4),
            )
        )
    )
    assert attached.kind == ninep.TATTACH + 1
    return directory


def walk(directory, names, *, from_fid=ROOT_FID, to_fid):
    """Walk `names` from `from_fid` to `to_fid`; gives the answer."""
    return Answer(
        directory(
            t(ninep.TWALK, (from_fid, 4), (to_fid, 4), (len(names), 2), *names)
        )
    )


def open_(directory, fid, flags=0):
    return Answer(directory(t(ninep.TLOPEN, (fid, 4), (flags, 4))))


class TestTheProtocolsNumbers:
    def test_are_linuxs(self):
        # 🎓 From Linux's include/net/9p/9p.h: a client and a server agree
        # on these or on nothing.
        assert (ninep.RLERROR, ninep.TSTATFS, ninep.TLOPEN) == (7, 8, 12)
        assert (ninep.TLCREATE, ninep.TSYMLINK, ninep.TREADLINK) == (14, 16, 22)
        assert (ninep.TGETATTR, ninep.TSETATTR, ninep.TREADDIR) == (24, 26, 40)
        assert (ninep.TFSYNC, ninep.TLOCK, ninep.TMKDIR) == (50, 52, 72)
        assert (ninep.TRENAMEAT, ninep.TUNLINKAT) == (74, 76)
        assert (ninep.TVERSION, ninep.TATTACH, ninep.TFLUSH) == (100, 104, 108)
        assert (ninep.TWALK, ninep.TREAD, ninep.TWRITE) == (110, 116, 118)
        assert ninep.TCLUNK == 120
        assert ninep.V9FS_MAGIC == 0x01021997


class TestWhenTheClientSaysWhichVersionItSpeaks:
    def test_the_servers_is_9p2000_l_and_a_size_no_bigger_than_asked(
        self, share
    ):
        directory = ninep.Directory(share)

        answer = Answer(directory(t(ninep.TVERSION, (8192, 4), b"9P2000.L")))

        assert (answer.kind, answer.tag) == (ninep.TVERSION + 1, TAG)
        assert answer.number(4) == 8192
        assert answer.string() == b"9P2000.L"

    def test_another_dialect_is_answered_unknown(self, share):
        directory = ninep.Directory(share)

        answer = Answer(directory(t(ninep.TVERSION, (8192, 4), b"9P2000.u")))

        answer.number(4)
        assert answer.string() == b"unknown"


class TestWhenTheClientAttaches:
    def test_the_fid_is_the_roots_and_its_qid_a_directorys(self, served):
        answer = walk(served, [], to_fid=2)

        assert answer.kind == ninep.TWALK + 1
        assert answer.number(2) == 0
        attached = Answer(
            served(t(ninep.TGETATTR, (2, 4), (ninep.GETATTR_BASIC, 8)))
        )
        attached.number(8)
        assert attached.qid()[0] == ninep.QTDIR


class TestWhenTheClientWalks:
    def test_a_name_at_a_time_gives_each_steps_qid(self, served, share):
        answer = walk(served, [b"eggs", b"ham.txt"], to_fid=2)

        assert answer.number(2) == 2
        assert answer.qid()[0] == ninep.QTDIR
        assert answer.qid() == (
            ninep.QTFILE,
            (share / "eggs" / "ham.txt").stat().st_ino,
        )

    def test_a_name_that_is_not_there_is_enoent(self, served):
        answer = walk(served, [b"beans"], to_fid=2)

        assert answer.error == ENOENT

    def test_a_walk_that_fails_after_a_step_gives_the_steps_made(self, served):
        answer = walk(served, [b"eggs", b"beans"], to_fid=2)

        assert answer.kind == ninep.TWALK + 1
        assert answer.number(2) == 1

    def test_dot_dot_at_the_root_stays_at_the_root(self, served, share):
        answer = walk(served, [b"..", b".."], to_fid=2)

        assert answer.number(2) == 2
        assert answer.qid()[1] == share.stat().st_ino

    def test_a_link_out_of_the_share_is_refused(self, served, share):
        os.symlink("/", share / "out")

        answer = walk(served, [b"out"], to_fid=2)

        assert answer.error == EACCES


class TestWhenTheClientReadsAFile:
    def test_opening_gives_its_qid_and_reading_its_bytes(self, served):
        walk(served, [b"spam.txt"], to_fid=2)

        opened = open_(served, 2)
        read = Answer(served(t(ninep.TREAD, (2, 4), (5, 8), (4, 4))))
        past_the_end = Answer(served(t(ninep.TREAD, (2, 4), (100, 8), (4, 4))))

        assert opened.qid()[0] == ninep.QTFILE
        assert read.bytes(read.number(4)) == b"spam"
        assert past_the_end.number(4) == 0

    def test_getattr_says_its_size_and_mode(self, served, share):
        walk(served, [b"spam.txt"], to_fid=2)

        answer = Answer(
            served(t(ninep.TGETATTR, (2, 4), (ninep.GETATTR_BASIC, 8)))
        )

        answer.number(8)
        answer.qid()
        mode = answer.number(4)
        answer.number(4), answer.number(4), answer.number(8), answer.number(8)
        assert answer.number(8) == 15
        assert mode == (share / "spam.txt").stat().st_mode


class TestWhenTheClientWritesAFile:
    def test_creating_then_writing_puts_the_bytes_in_the_share(
        self, served, share
    ):
        walk(served, [], to_fid=2)

        created = Answer(
            served(
                t(
                    ninep.TLCREATE,
                    (2, 4),
                    b"new.txt",
                    (0o101, 4),
                    (0o644, 4),
                    (0, 4),
                )
            )
        )
        written = Answer(
            served(
                t(
                    ninep.TWRITE,
                    (2, 4),
                    (0, 8),
                    (5, 4),
                    (0x6D617073, 4),
                    (0x21, 1),
                )
            )
        )
        Answer(served(t(ninep.TCLUNK, (2, 4))))

        assert created.qid()[0] == ninep.QTFILE
        assert written.number(4) == 5
        assert (share / "new.txt").read_bytes() == b"spam!"

    def test_truncating_by_setattr_cuts_the_file(self, served, share):
        walk(served, [b"spam.txt"], to_fid=2)

        answer = Answer(
            served(
                t(
                    ninep.TSETATTR,
                    (2, 4),
                    (ninep.SETATTR_SIZE, 4),
                    (0, 4),
                    (0, 4),
                    (0, 4),
                    (4, 8),
                    (0, 8),
                    (0, 8),
                    (0, 8),
                    (0, 8),
                )
            )
        )

        assert answer.kind == ninep.TSETATTR + 1
        assert (share / "spam.txt").read_bytes() == b"spam"


class TestWhenTheClientListsADirectory:
    def test_the_entries_come_with_their_kinds_in_order_after_dot_and_dot_dot(
        self, served
    ):
        walk(served, [], to_fid=2)
        open_(served, 2)

        answer = Answer(served(t(ninep.TREADDIR, (2, 4), (0, 8), (4096, 4))))

        entries = []
        count = answer.number(4)
        end = answer.at + count
        while answer.at < end:
            answer.qid()
            answer.number(8)
            entries.append((answer.number(1), answer.string()))
        assert entries == [
            (ninep.DT_DIR, b"."),
            (ninep.DT_DIR, b".."),
            (ninep.DT_DIR, b"eggs"),
            (ninep.DT_REG, b"spam.txt"),
        ]

    def test_reading_on_from_an_entrys_offset_gives_the_ones_after_it(
        self, served
    ):
        walk(served, [], to_fid=2)
        open_(served, 2)

        answer = Answer(served(t(ninep.TREADDIR, (2, 4), (3, 8), (4096, 4))))

        answer.number(4)
        answer.qid()
        answer.number(8)
        answer.number(1)
        assert answer.string() == b"spam.txt"

    def test_reading_entries_of_a_directory_not_opened_is_ebadf(self, served):
        walk(served, [], to_fid=2)

        answer = Answer(served(t(ninep.TREADDIR, (2, 4), (0, 8), (4096, 4))))

        assert answer.error == EBADF


class TestWhenTheClientAsksHowFullTheShareIs:
    def test_statfs_says_9p_and_the_blocks_of_the_shares_file_system(
        self, served, share
    ):
        answer = Answer(served(t(ninep.TSTATFS, (ROOT_FID, 4))))

        assert answer.kind == ninep.TSTATFS + 1
        assert answer.number(4) == ninep.V9FS_MAGIC
        block_size, blocks = answer.number(4), answer.number(8)
        found = os.statvfs(share)
        assert block_size * blocks == found.f_frsize * found.f_blocks


class TestWhenTheClientMakesAndRemovesThings:
    def test_mkdir_then_unlinkat_with_removedir(self, served, share):
        walk(served, [], to_fid=2)

        made = Answer(
            served(t(ninep.TMKDIR, (2, 4), b"beans", (0o755, 4), (0, 4)))
        )
        assert made.qid()[0] == ninep.QTDIR
        assert (share / "beans").is_dir()

        removed = Answer(
            served(
                t(ninep.TUNLINKAT, (2, 4), b"beans", (ninep.AT_REMOVEDIR, 4))
            )
        )
        assert removed.kind == ninep.TUNLINKAT + 1
        assert not (share / "beans").exists()

    def test_renameat_moves_a_file_between_directories(self, served, share):
        walk(served, [], to_fid=2)
        walk(served, [b"eggs"], to_fid=3)

        answer = Answer(
            served(
                t(ninep.TRENAMEAT, (2, 4), b"spam.txt", (3, 4), b"moved.txt")
            )
        )

        assert answer.kind == ninep.TRENAMEAT + 1
        assert (
            share / "eggs" / "moved.txt"
        ).read_bytes() == b"spam spam spam\n"

    def test_symlink_then_readlink(self, served, share):
        walk(served, [], to_fid=2)

        made = Answer(
            served(t(ninep.TSYMLINK, (2, 4), b"link", b"spam.txt", (0, 4)))
        )
        walk(served, [b"link"], to_fid=3)
        read = Answer(served(t(ninep.TREADLINK, (3, 4))))

        assert made.qid()[0] == ninep.QTSYMLINK
        assert read.string() == b"spam.txt"


class TestWhenALinkMadeSinceLeadsAFidOutOfTheShare:
    def test_using_the_fid_is_refused(self, served, share):
        walk(served, [], to_fid=2)
        Answer(served(t(ninep.TMKDIR, (2, 4), b"d", (0o755, 4), (0, 4))))
        walk(served, [b"d"], to_fid=3)
        Answer(
            served(t(ninep.TUNLINKAT, (2, 4), b"d", (ninep.AT_REMOVEDIR, 4)))
        )
        Answer(served(t(ninep.TSYMLINK, (2, 4), b"d", b"/", (0, 4))))

        answer = open_(served, 3)

        assert answer.error == EACCES


class TestWhenTheClientAsksWhatTheServerHasNot:
    def test_it_is_answered_rlerror_eopnotsupp_under_the_same_tag(self, served):
        answer = Answer(served(t(ninep.TLOCK, (2, 4))))

        assert answer.tag == TAG
        assert answer.error == EOPNOTSUPP

    def test_a_fid_never_attached_is_ebadf(self, served):
        answer = open_(served, 99)

        assert answer.error == EBADF
