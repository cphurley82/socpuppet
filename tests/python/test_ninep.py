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
ELOOP = 40
EOPNOTSUPP = 95
ROOT_FID = 1
TAG = 0x1234


class Data(bytes):
    """Bytes that go into a message as they are, where `bytes` are a string."""


def t(kind, *fields):
    """A T-message of `kind` with `fields`.

    An int is given as (value, width), `bytes` are a 9P string, its length
    and then its bytes, and `Data` goes in as it is.
    """
    body = b"".join(
        each
        if isinstance(each, Data)
        else struct.pack("<H", len(each)) + each
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
    def read_to_the_end(self):
        """Whether every byte of the body has been read."""
        return self.at == len(self.body)

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


def setattr_(directory, fid, valid, *, mode=0, size=0, atime=0, mtime=0):
    """Tsetattr of `fid`, with what `valid` says set: times in whole seconds."""
    return Answer(
        directory(
            t(
                ninep.TSETATTR,
                (fid, 4),
                (valid, 4),
                (mode, 4),
                (os.getuid(), 4),
                (os.getgid(), 4),
                (size, 8),
                (atime, 8),
                (0, 8),
                (mtime, 8),
                (0, 8),
            )
        )
    )


def getattr_(directory, fid):
    """Rgetattr of `fid`, read: its fields by name, and whether that was all."""
    answer = Answer(
        directory(t(ninep.TGETATTR, (fid, 4), (ninep.GETATTR_BASIC, 8)))
    )
    names = [
        "valid",
        "qid",
        "mode",
        "uid",
        "gid",
        "nlink",
        "rdev",
        "size",
        "blksize",
        "blocks",
        "atime",
        "atime_nsec",
        "mtime",
        "mtime_nsec",
        "ctime",
        "ctime_nsec",
        "btime",
        "btime_nsec",
        "gen",
        "data_version",
    ]
    widths = dict.fromkeys(names, 8) | {"mode": 4, "uid": 4, "gid": 4}
    fields = {
        name: answer.qid() if name == "qid" else answer.number(widths[name])
        for name in names
    }
    return fields, answer.read_to_the_end


def unlinkat(directory, fid, name, flags=0):
    return Answer(directory(t(ninep.TUNLINKAT, (fid, 4), name, (flags, 4))))


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
    def test_the_answer_is_the_roots_qid_a_directorys(self, share):
        directory = ninep.Directory(share)
        directory(t(ninep.TVERSION, (65536, 4), b"9P2000.L"))

        answer = Answer(
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

        assert answer.qid() == (ninep.QTDIR, share.stat().st_ino)


class TestWhenTheClientSaysWhichVersionAgain:
    def test_every_fid_it_had_is_forgotten(self, served):
        served(t(ninep.TVERSION, (65536, 4), b"9P2000.L"))

        answer = open_(served, ROOT_FID)

        assert answer.error == EBADF


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

    def test_to_a_link_out_of_the_share_gives_the_links_own_qid(
        self, served, share
    ):
        # 🎓 A 9P server never follows a link: the client reads it and
        # walks where it says, in its own tree.
        os.symlink("/", share / "out")

        answer = walk(served, [b"out"], to_fid=2)

        assert answer.number(2) == 1
        assert answer.qid() == (ninep.QTSYMLINK, (share / "out").lstat().st_ino)

    def test_through_a_link_out_of_the_share_is_refused(self, served, share):
        os.symlink("/", share / "out")

        answer = walk(served, [b"out", b"etc"], to_fid=2)

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

    def test_getattr_says_its_size_and_mode_and_nothing_after_the_last_field(
        self, served, share
    ):
        walk(served, [b"spam.txt"], to_fid=2)

        fields, read_to_the_end = getattr_(served, 2)

        assert fields["size"] == 15
        assert fields["mode"] == (share / "spam.txt").stat().st_mode
        assert read_to_the_end


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
            served(t(ninep.TWRITE, (2, 4), (0, 8), (5, 4), Data(b"spam!")))
        )
        served(t(ninep.TCLUNK, (2, 4)))

        assert created.qid()[0] == ninep.QTFILE
        assert written.number(4) == 5
        assert (share / "new.txt").read_bytes() == b"spam!"

    def test_creating_a_name_that_is_there_exclusively_is_eexist(self, served):
        walk(served, [], to_fid=2)
        exclusively = ninep.O_CREAT | ninep.O_EXCL | 1

        answer = Answer(
            served(
                t(
                    ninep.TLCREATE,
                    (2, 4),
                    b"spam.txt",
                    (exclusively, 4),
                    (0o644, 4),
                    (0, 4),
                )
            )
        )

        assert answer.error == EEXIST

    def test_opening_to_truncate_empties_the_file(self, served, share):
        walk(served, [b"spam.txt"], to_fid=2)

        open_(served, 2, flags=ninep.O_TRUNC | 1)

        assert (share / "spam.txt").read_bytes() == b""

    def test_fsync_of_an_open_file_is_answered(self, served):
        walk(served, [b"spam.txt"], to_fid=2)
        open_(served, 2, flags=1)

        answer = Answer(served(t(ninep.TFSYNC, (2, 4), (0, 4))))

        assert answer.kind == ninep.TFSYNC + 1


class TestWhenTheClientSetsAttributes:
    def test_a_size_cuts_the_file(self, served, share):
        walk(served, [b"spam.txt"], to_fid=2)

        answer = setattr_(served, 2, ninep.SETATTR_SIZE, size=4)

        assert answer.kind == ninep.TSETATTR + 1
        assert (share / "spam.txt").read_bytes() == b"spam"

    def test_a_mode_changes_the_permissions(self, served, share):
        walk(served, [b"spam.txt"], to_fid=2)

        setattr_(served, 2, ninep.SETATTR_MODE, mode=0o600)

        assert (share / "spam.txt").stat().st_mode & 0o777 == 0o600

    def test_a_time_given_is_set_and_one_not_asked_for_is_kept(
        self, served, share
    ):
        walk(served, [b"spam.txt"], to_fid=2)
        accessed = (share / "spam.txt").stat().st_atime_ns

        setattr_(
            served,
            2,
            ninep.SETATTR_MTIME | ninep.SETATTR_MTIME_SET,
            mtime=1_000_000_000,
        )

        found = (share / "spam.txt").stat()
        assert found.st_mtime_ns == 1_000_000_000 * 10**9
        assert found.st_atime_ns == accessed

    def test_its_own_owner_and_group_are_taken(self, served):
        walk(served, [b"spam.txt"], to_fid=2)

        answer = setattr_(served, 2, ninep.SETATTR_UID | ninep.SETATTR_GID)

        assert answer.kind == ninep.TSETATTR + 1

    def test_a_mode_or_size_for_a_link_is_eloop_and_its_target_untouched(
        self, served, share, tmp_path_factory
    ):
        outside = tmp_path_factory.mktemp("outside") / "eggs.txt"
        outside.write_bytes(b"eggs")
        outside.chmod(0o644)
        os.symlink(outside, share / "out")
        walk(served, [b"out"], to_fid=2)

        moded = setattr_(served, 2, ninep.SETATTR_MODE, mode=0o600)
        sized = setattr_(served, 2, ninep.SETATTR_SIZE, size=0)

        assert (moded.error, sized.error) == (ELOOP, ELOOP)
        assert outside.stat().st_mode & 0o777 == 0o644
        assert outside.read_bytes() == b"eggs"

    def test_creating_over_a_link_is_eloop_and_its_target_untouched(
        self, served, share, tmp_path_factory
    ):
        outside = tmp_path_factory.mktemp("outside") / "eggs.txt"
        outside.write_bytes(b"eggs")
        os.symlink(outside, share / "out")
        walk(served, [], to_fid=2)

        answer = Answer(
            served(
                t(
                    ninep.TLCREATE,
                    (2, 4),
                    b"out",
                    (ninep.O_TRUNC | 1, 4),
                    (0o644, 4),
                    (0, 4),
                )
            )
        )

        assert answer.error == ELOOP
        assert outside.read_bytes() == b"eggs"

    def test_a_time_too_big_for_this_machine_is_einval(self, served):
        walk(served, [b"spam.txt"], to_fid=2)

        answer = setattr_(
            served,
            2,
            ninep.SETATTR_MTIME | ninep.SETATTR_MTIME_SET,
            mtime=2**63,
        )

        assert answer.error == EINVAL


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


class TestWhenTheClientMakesThings:
    def test_mkdir_makes_a_directory_and_gives_its_qid(self, served, share):
        walk(served, [], to_fid=2)

        made = Answer(
            served(t(ninep.TMKDIR, (2, 4), b"beans", (0o755, 4), (0, 4)))
        )

        assert made.qid()[0] == ninep.QTDIR
        assert (share / "beans").is_dir()

    def test_a_symlink_made_reads_back_as_its_target(self, served):
        walk(served, [], to_fid=2)
        made = Answer(
            served(t(ninep.TSYMLINK, (2, 4), b"link", b"spam.txt", (0, 4)))
        )
        walk(served, [b"link"], to_fid=3)

        read = Answer(served(t(ninep.TREADLINK, (3, 4))))

        assert made.qid()[0] == ninep.QTSYMLINK
        assert read.string() == b"spam.txt"


class TestWhenTheClientRemovesThings:
    def test_unlinkat_with_removedir_removes_a_directory(self, served, share):
        (share / "beans").mkdir()
        walk(served, [], to_fid=2)

        removed = unlinkat(served, 2, b"beans", ninep.AT_REMOVEDIR)

        assert removed.kind == ninep.TUNLINKAT + 1
        assert not (share / "beans").exists()

    def test_a_link_out_of_the_share_can_be_read_and_removed(
        self, served, share
    ):
        os.symlink("/bin/sh", share / "out")
        walk(served, [], to_fid=2)
        walk(served, [b"out"], to_fid=3)

        read = Answer(served(t(ninep.TREADLINK, (3, 4))))
        removed = unlinkat(served, 2, b"out")

        assert read.string() == b"/bin/sh"
        assert removed.kind == ninep.TUNLINKAT + 1
        assert not (share / "out").is_symlink()


class TestWhenTheClientRenames:
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

    def test_a_fid_on_what_moved_follows_it(self, served):
        # 🎓 Linux keeps a renamed file's fid, and asks about it by that.
        walk(served, [], to_fid=2)
        walk(served, [b"eggs", b"ham.txt"], to_fid=3)

        served(t(ninep.TRENAMEAT, (2, 4), b"eggs", (2, 4), b"beans"))
        fields, _ = getattr_(served, 3)

        assert fields["size"] == 3


class TestWhenALinkMadeSinceLeadsAFidOutOfTheShare:
    def test_using_the_fid_is_refused(self, served, share):
        (share / "d" / "e").mkdir(parents=True)
        walk(served, [b"d", b"e"], to_fid=3)
        (share / "d" / "e").rmdir()
        (share / "d").rmdir()
        (share / "d").symlink_to("/")

        answer = open_(served, 3)

        assert answer.error == EACCES

    def test_opening_a_fid_that_has_become_a_link_is_eloop(self, served, share):
        (share / "d").mkdir()
        walk(served, [b"d"], to_fid=3)
        (share / "d").rmdir()
        (share / "d").symlink_to("/")

        answer = open_(served, 3)

        assert answer.error == ELOOP


class TestWhenTheClientSendsWhatTheServerCannotRead:
    def test_a_message_too_short_for_its_header_is_einval_with_no_tag(
        self, served
    ):
        answer = Answer(served(b"\x05\x00\x00"))

        assert answer.tag == ninep.NO_TAG
        assert answer.error == EINVAL


class TestWhenTheClientAsksWhatTheServerHasNot:
    def test_it_is_answered_rlerror_eopnotsupp_under_the_same_tag(self, served):
        answer = Answer(served(t(ninep.TLOCK, (2, 4))))

        assert answer.tag == TAG
        assert answer.error == EOPNOTSUPP


class TestWhenTheClientNamesAFidItNeverMade:
    def test_it_is_ebadf(self, served):
        answer = open_(served, 99)

        assert answer.error == EBADF
