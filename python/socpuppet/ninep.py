"""🧵 Python serving a directory over 9P2000.L, as virtio-9p carries it.

🎓 9P is Plan 9's file protocol, and 9P2000.L is the dialect Linux's
client speaks to a server that keeps Linux's own file attributes. A
client sends a T-message and the server answers with the R-message of the
same number plus one, under the same tag; what went wrong is an `Rlerror`
with Linux's errno. Each message is `size[4] type[1] tag[2]` and a body
whose numbers are little-endian and whose strings are `length[2] bytes`.

A **fid** is the client's name for a place in the tree it has walked to:
`Tattach` gives the first one, the root, `Twalk` makes another from it a
name at a time, `Tlopen` opens what one names, and `Tclunk` lets it go.
A **qid** is the server's name for a file, `type[1] version[4] path[8]`:
whether it is a directory, a link or a file, a version that changes when
it does, and a number that is its inode's.

`Directory` serves a directory of this machine this way, one request at a
time, as `socpuppet.fuse.Directory` serves one over FUSE. ⚠️ A client
may change anything under the directory, and nothing outside it. The
server never follows a link at the end of a path, as 9P's servers do not:
the client reads the link and walks where it says. A path that leads out
of the share through a directory, by `..` or by a link, is refused.
"""

from __future__ import annotations

import os
import stat
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from socpuppet.fuse import linux_errno, linux_errno_named

#: The version of the protocol spoken here, and the answer to any other.
VERSION = b"9P2000.L"
UNKNOWN_VERSION = b"unknown"
#: The most a message may be, which a client may ask for less of.
MAX_MESSAGE_SIZE = 512 * 1024
#: The fid a client sends for "none", and the tag of an answer to a message
#: whose own tag could not be read.
NO_FID = 0xFFFF_FFFF
NO_TAG = 0xFFFF

#: The message types of 9P2000.L: each T-message's number, its R-message
#: being the next.
RLERROR = 7
TSTATFS = 8
TLOPEN = 12
TLCREATE = 14
TSYMLINK = 16
TREADLINK = 22
TGETATTR = 24
TSETATTR = 26
TREADDIR = 40
TFSYNC = 50
TLOCK = 52
TMKDIR = 72
TRENAMEAT = 74
TUNLINKAT = 76
TVERSION = 100
TATTACH = 104
TFLUSH = 108
TWALK = 110
TREAD = 116
TWRITE = 118
TCLUNK = 120

#: A qid's type: what kind of file it names.
QTDIR = 0x80
QTSYMLINK = 0x02
QTFILE = 0x00

#: What Tgetattr may ask for, and what is answered: everything but the
#: birth time, the generation and the data version, which are Linux's.
GETATTR_BASIC = 0x0000_07FF
#: Tsetattr's `valid` bits.
SETATTR_MODE = 0x01
SETATTR_UID = 0x02
SETATTR_GID = 0x04
SETATTR_SIZE = 0x08
SETATTR_ATIME = 0x10
SETATTR_MTIME = 0x20
SETATTR_ATIME_SET = 0x80
SETATTR_MTIME_SET = 0x100
#: Tunlinkat's flag for a directory.
AT_REMOVEDIR = 0x200
#: Linux's `d_type`, what kind of file a directory entry names.
DT_UNKNOWN = 0
DT_DIR = 4
DT_REG = 8
DT_LNK = 10
#: What statfs says the file system is: Linux's number for 9P (V9FS_MAGIC).
V9FS_MAGIC = 0x0102_1997
#: Linux's numbers for the open flags a client sends: the access mode is
#: the low two bits, and these are the rest that matter here.
O_ACCMODE = 0o3
O_CREAT = 0o100
O_EXCL = 0o200
O_TRUNC = 0o1000
O_APPEND = 0o2000

HEADER = struct.Struct("<IBH")
#: What an Rread or an Rreaddir holds before its data: the header, and the
#: count of bytes that follow.
_COUNTED_HEADER_SIZE = HEADER.size + 4


class _Refused(Exception):
    """A request that is answered with `Rlerror`, by its errno's name."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.number = linux_errno_named(name)


@dataclass
class Fid:
    """What a fid names: a path, and the file if it is open."""

    path: Path
    file: IO[bytes] | None = None
    #: An open directory's entries, as the client reads them: (qid, type,
    #: name).
    entries: list[tuple[bytes, int, bytes]] | None = None


class _Reader:
    """A message body, read field by field."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.at = 0

    def number(self, width: int, *, signed: bool = False) -> int:
        value = int.from_bytes(
            self.body[self.at : self.at + width], "little", signed=signed
        )
        self.at += width
        return value

    def time(self) -> tuple[int, int]:
        """A time as Tsetattr gives it: signed seconds, then nanoseconds."""
        return self.number(8, signed=True), self.number(8)

    def string(self) -> bytes:
        length = self.number(2)
        text = self.body[self.at : self.at + length]
        self.at += length
        return text

    def bytes(self, count: int) -> bytes:
        data = self.body[self.at : self.at + count]
        self.at += count
        return data


def _string(text: bytes) -> bytes:
    return len(text).to_bytes(2, "little") + text


def _number(value: int, width: int) -> bytes:
    return value.to_bytes(width, "little", signed=False)


class Directory:
    """🎭 Serves the directory `root` over 9P2000.L, one request at a time.

    Call it with a T-message's bytes, and it gives the R-message's.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self._fids: dict[int, Fid] = {}
        #: The most a message may be, as Tversion agreed it.
        self._message_size = MAX_MESSAGE_SIZE
        self._handlers: dict[int, Callable[[_Reader], bytes]] = {
            TVERSION: self._version,
            TATTACH: self._attach,
            TFLUSH: self._flush,
            TWALK: self._walk,
            TLOPEN: self._lopen,
            TLCREATE: self._lcreate,
            TREAD: self._read,
            TWRITE: self._write,
            TCLUNK: self._clunk,
            TGETATTR: self._getattr,
            TSETATTR: self._setattr,
            TREADDIR: self._readdir,
            TMKDIR: self._mkdir,
            TUNLINKAT: self._unlinkat,
            TRENAMEAT: self._renameat,
            TSYMLINK: self._symlink,
            TREADLINK: self._readlink,
            TSTATFS: self._statfs,
            TFSYNC: self._fsync,
        }

    def __call__(self, request: bytes) -> bytes:
        """The R-message that answers the T-message `request`, as bytes.

        One that cannot be read, or asks what this machine cannot do, is
        answered `EINVAL`, as `socpuppet.fuse` answers one.
        """
        try:
            size, kind, tag = HEADER.unpack_from(request)
        except struct.error:
            return self._lerror(NO_TAG, linux_errno_named("EINVAL"))
        body = _Reader(request[HEADER.size : size])
        try:
            handler = self._handlers.get(kind)
            if handler is None:
                raise _Refused("EOPNOTSUPP")
            kind, answer = kind + 1, handler(body)
        except _Refused as refused:
            kind, answer = RLERROR, _number(refused.number, 4)
        except OSError as failure:
            kind, answer = RLERROR, _number(linux_errno(failure), 4)
        except (ValueError, OverflowError):
            kind, answer = RLERROR, _number(linux_errno_named("EINVAL"), 4)
        return HEADER.pack(HEADER.size + len(answer), kind, tag) + answer

    @staticmethod
    def _lerror(tag: int, number: int) -> bytes:
        answer = _number(number, 4)
        return HEADER.pack(HEADER.size + len(answer), RLERROR, tag) + answer

    # Where fids point, kept inside the share.

    def _fid(self, number: int) -> Fid:
        """What fid `number` names, checked to be inside the share still.

        It was when walked to, and a link made since in place of one of
        the directories it is in can have led it out.
        """
        try:
            fid = self._fids[number]
        except KeyError:
            raise _Refused("EBADF") from None
        if not self._inside(fid.path):
            raise _Refused("EACCES")
        return fid

    def _inside(self, path: Path) -> bool:
        """Whether `path` is in the share, its last name not followed."""
        if path == self.root:
            return True
        return (path.parent.resolve() / path.name).is_relative_to(self.root)

    def _child(
        self, parent: Path, name: bytes, *, changing: bool = True
    ) -> Path:
        """Where `name` in the directory `parent` is, if it is inside.

        `..` names a directory to walk to, never one to change. `.` is
        refused everywhere: Linux's client never sends it.
        """
        text = name.decode(errors="surrogateescape")
        if not text or "/" in text or text == ".":
            raise _Refused("EINVAL")
        if text == "..":
            if changing:
                raise _Refused("EINVAL")
            return self._above(parent)
        child = parent / text
        if not self._inside(child):
            raise _Refused("EACCES")
        return child

    def _above(self, directory: Path) -> Path:
        """The directory above `directory`, which at the root is the root."""
        return directory if directory == self.root else directory.parent

    def _qid(self, path: Path) -> bytes:
        found = path.lstat()
        if stat.S_ISDIR(found.st_mode):
            kind = QTDIR
        elif stat.S_ISLNK(found.st_mode):
            kind = QTSYMLINK
        else:
            kind = QTFILE
        return (
            _number(kind, 1)
            + _number(int(found.st_mtime) & 0xFFFF_FFFF, 4)
            + _number(found.st_ino & 0xFFFF_FFFF_FFFF_FFFF, 8)
        )

    # The messages.

    def _version(self, body: _Reader) -> bytes:
        size = body.number(4)
        version = body.string()
        for number in list(self._fids):
            self._let_go(number)
        agreed = VERSION if version.startswith(VERSION) else UNKNOWN_VERSION
        self._message_size = min(size, MAX_MESSAGE_SIZE)
        return _number(self._message_size, 4) + _string(agreed)

    def _attach(self, body: _Reader) -> bytes:
        fid = body.number(4)
        self._fids[fid] = Fid(self.root)
        return self._qid(self.root)

    def _flush(self, body: _Reader) -> bytes:
        # Nothing is in flight: a request is answered as it arrives.
        return b""

    def _walk(self, body: _Reader) -> bytes:
        fid = body.number(4)
        new_fid = body.number(4)
        names = [body.string() for _ in range(body.number(2))]
        path = self._fid(fid).path
        qids: list[bytes] = []
        for name in names:
            child = self._child(path, name, changing=False)
            if not child.exists(follow_symlinks=False):
                if not qids:
                    raise _Refused("ENOENT")
                break
            path = child
            qids.append(self._qid(path))
        if len(qids) == len(names):
            self._fids[new_fid] = Fid(path)
        return _number(len(qids), 2) + b"".join(qids)

    def _lopen(self, body: _Reader) -> bytes:
        fid = self._fid(body.number(4))
        flags = body.number(4)
        if fid.path.is_symlink():
            raise _Refused("ELOOP")
        if fid.path.is_dir():
            fid.entries = self._listing(fid.path)
        else:
            fid.file = _open(fid.path, flags)
        return self._qid(fid.path) + _number(0, 4)

    def _lcreate(self, body: _Reader) -> bytes:
        fid = self._fid(body.number(4))
        name = body.string()
        flags = body.number(4)
        mode = body.number(4)
        created = self._child(fid.path, name)
        fid.file = _open(created, flags | O_CREAT, mode)
        fid.path = created
        return self._qid(created) + _number(0, 4)

    def _read(self, body: _Reader) -> bytes:
        fid = self._fid(body.number(4))
        offset = body.number(8)
        count = self._fitting(body.number(4))
        if fid.file is None:
            raise _Refused("EBADF")
        data = os.pread(fid.file.fileno(), count, offset)
        return _number(len(data), 4) + data

    def _fitting(self, count: int) -> int:
        """`count`, or less if its answer would not fit in one message."""
        return min(count, self._message_size - _COUNTED_HEADER_SIZE)

    def _write(self, body: _Reader) -> bytes:
        fid = self._fid(body.number(4))
        offset = body.number(8)
        data = body.bytes(body.number(4))
        if fid.file is None:
            raise _Refused("EBADF")
        written = os.pwrite(fid.file.fileno(), data, offset)
        return _number(written, 4)

    def _clunk(self, body: _Reader) -> bytes:
        self._let_go(body.number(4))
        return b""

    def _let_go(self, number: int) -> None:
        """Forget fid `number`, closing what it had open."""
        fid = self._fids.pop(number, None)
        if fid is not None and fid.file is not None:
            fid.file.close()

    def _getattr(self, body: _Reader) -> bytes:
        fid = self._fid(body.number(4))
        body.number(8)  # What is asked for: everything basic is given.
        found = fid.path.lstat()
        return (
            _number(GETATTR_BASIC, 8)
            + self._qid(fid.path)
            + _number(found.st_mode, 4)
            + _number(found.st_uid, 4)
            + _number(found.st_gid, 4)
            + _number(found.st_nlink, 8)
            + _number(found.st_rdev, 8)
            + _number(found.st_size, 8)
            + _number(found.st_blksize, 8)
            + _number(found.st_blocks, 8)
            + _time_fields(found.st_atime_ns)
            + _time_fields(found.st_mtime_ns)
            + _time_fields(found.st_ctime_ns)
            + _number(0, 8) * 4
        )

    def _setattr(self, body: _Reader) -> bytes:
        fid = self._fid(body.number(4))
        valid = body.number(4)
        mode = body.number(4)
        uid = body.number(4)
        gid = body.number(4)
        size = body.number(8)
        atime = body.time()
        mtime = body.time()
        path = fid.path
        # ⚠️ A link's own mode and size cannot be set, and setting them on
        # its target would reach outside the share.
        if valid & (SETATTR_MODE | SETATTR_SIZE) and path.is_symlink():
            raise _Refused("ELOOP")
        if valid & SETATTR_MODE:
            path.chmod(stat.S_IMODE(mode))
        if valid & (SETATTR_UID | SETATTR_GID):
            os.chown(
                path,
                uid if valid & SETATTR_UID else -1,
                gid if valid & SETATTR_GID else -1,
                follow_symlinks=False,
            )
        if valid & SETATTR_SIZE:
            os.truncate(path, size)
        if valid & (SETATTR_ATIME | SETATTR_MTIME):
            found = path.lstat()
            now = time.time_ns()
            os.utime(
                path,
                follow_symlinks=False,
                ns=(
                    _time(
                        valid,
                        SETATTR_ATIME,
                        SETATTR_ATIME_SET,
                        atime,
                        now,
                        found.st_atime_ns,
                    ),
                    _time(
                        valid,
                        SETATTR_MTIME,
                        SETATTR_MTIME_SET,
                        mtime,
                        now,
                        found.st_mtime_ns,
                    ),
                ),
            )
        return b""

    def _listing(self, path: Path) -> list[tuple[bytes, int, bytes]]:
        entries = [
            (self._qid(path), DT_DIR, b"."),
            (self._qid(self._above(path)), DT_DIR, b".."),
        ]
        for child in sorted(path.iterdir()):
            kind = _dirent_type(child.lstat().st_mode)
            name = child.name.encode(errors="surrogateescape")
            entries.append((self._qid(child), kind, name))
        return entries

    def _readdir(self, body: _Reader) -> bytes:
        fid = self._fid(body.number(4))
        offset = body.number(8)
        count = self._fitting(body.number(4))
        if fid.entries is None:
            raise _Refused("EBADF")
        data = b""
        for index in range(offset, len(fid.entries)):
            qid, kind, name = fid.entries[index]
            entry = (
                qid + _number(index + 1, 8) + _number(kind, 1) + _string(name)
            )
            if len(data) + len(entry) > count:
                break
            data += entry
        return _number(len(data), 4) + data

    def _mkdir(self, body: _Reader) -> bytes:
        parent = self._fid(body.number(4)).path
        made = self._child(parent, body.string())
        made.mkdir(mode=stat.S_IMODE(body.number(4)))
        return self._qid(made)

    def _unlinkat(self, body: _Reader) -> bytes:
        parent = self._fid(body.number(4)).path
        target = self._child(parent, body.string())
        if body.number(4) & AT_REMOVEDIR:
            target.rmdir()
        else:
            target.unlink()
        return b""

    def _renameat(self, body: _Reader) -> bytes:
        old_parent = self._fid(body.number(4)).path
        old = self._child(old_parent, body.string())
        new_parent = self._fid(body.number(4)).path
        new = self._child(new_parent, body.string())
        old.rename(new)
        for fid in self._fids.values():
            if fid.path.is_relative_to(old):
                fid.path = new / fid.path.relative_to(old)
        return b""

    def _symlink(self, body: _Reader) -> bytes:
        parent = self._fid(body.number(4)).path
        link = self._child(parent, body.string())
        target = body.string().decode(errors="surrogateescape")
        link.symlink_to(target)
        return self._qid(link)

    def _readlink(self, body: _Reader) -> bytes:
        fid = self._fid(body.number(4))
        return _string(os.readlink(fid.path).encode(errors="surrogateescape"))

    def _statfs(self, body: _Reader) -> bytes:
        self._fid(body.number(4))
        found = os.statvfs(self.root)
        return (
            _number(V9FS_MAGIC, 4)
            + _number(found.f_frsize, 4)
            + _number(found.f_blocks, 8)
            + _number(found.f_bfree, 8)
            + _number(found.f_bavail, 8)
            + _number(found.f_files, 8)
            + _number(found.f_ffree, 8)
            + _number(0, 8)
            + _number(found.f_namemax, 4)
        )

    def _fsync(self, body: _Reader) -> bytes:
        fid = self._fid(body.number(4))
        if fid.file is not None:
            os.fsync(fid.file.fileno())
        return b""


def _open(path: Path, flags: int, mode: int = 0o644) -> IO[bytes]:
    """The file at `path`, opened as Linux's `flags` say, and not a link."""
    access = flags & O_ACCMODE
    # ⚠️ Never through a link: its target can be outside the share.
    host_flags = os.O_NOFOLLOW | {
        0: os.O_RDONLY,
        1: os.O_WRONLY,
        2: os.O_RDWR,
    }.get(access, os.O_RDWR)
    for theirs, ours in (
        (O_CREAT, os.O_CREAT),
        (O_EXCL, os.O_EXCL),
        (O_TRUNC, os.O_TRUNC),
        (O_APPEND, os.O_APPEND),
    ):
        if flags & theirs:
            host_flags |= ours
    opened = os.open(path, host_flags, stat.S_IMODE(mode))
    return os.fdopen(opened, "rb" if access == 0 else "r+b", buffering=0)


def _time(
    valid: int,
    set_bit: int,
    given_bit: int,
    given: tuple[int, int],
    now: int,
    kept: int,
) -> int:
    """A time Tsetattr sets, in ns: now, the one given, or the file's own.

    The one given is its seconds and its nanoseconds, which are refused if
    they make a second or more, as Linux's utimensat refuses them.
    """
    if not valid & set_bit:
        return kept
    if not valid & given_bit:
        return now
    seconds, nanoseconds = given
    if nanoseconds >= 1_000_000_000:
        raise _Refused("EINVAL")
    return seconds * 1_000_000_000 + nanoseconds


def _time_fields(ns: int) -> bytes:
    """A time as Rgetattr gives it: seconds, then nanoseconds left over.

    🎓 The seconds go as a two's-complement 64-bit number, which Linux reads
    back as a signed one, so a time before 1970 is negative.
    """
    seconds, nanoseconds = divmod(ns, 1_000_000_000)
    return _number(seconds & 0xFFFF_FFFF_FFFF_FFFF, 8) + _number(nanoseconds, 8)


def _dirent_type(mode: int) -> int:
    """Linux's `d_type` for a file of `mode`, as Treaddir's entries carry it."""
    if stat.S_ISDIR(mode):
        return DT_DIR
    if stat.S_ISLNK(mode):
        return DT_LNK
    if stat.S_ISREG(mode):
        return DT_REG
    return DT_UNKNOWN


__all__ = [
    "AT_REMOVEDIR",
    "DT_DIR",
    "DT_LNK",
    "DT_REG",
    "DT_UNKNOWN",
    "GETATTR_BASIC",
    "HEADER",
    "MAX_MESSAGE_SIZE",
    "NO_FID",
    "NO_TAG",
    "O_ACCMODE",
    "O_APPEND",
    "O_CREAT",
    "O_EXCL",
    "O_TRUNC",
    "QTDIR",
    "QTFILE",
    "QTSYMLINK",
    "RLERROR",
    "SETATTR_ATIME",
    "SETATTR_ATIME_SET",
    "SETATTR_GID",
    "SETATTR_MODE",
    "SETATTR_MTIME",
    "SETATTR_MTIME_SET",
    "SETATTR_SIZE",
    "SETATTR_UID",
    "TATTACH",
    "TCLUNK",
    "TFLUSH",
    "TFSYNC",
    "TGETATTR",
    "TLCREATE",
    "TLOCK",
    "TLOPEN",
    "TMKDIR",
    "TREAD",
    "TREADDIR",
    "TREADLINK",
    "TRENAMEAT",
    "TSETATTR",
    "TSTATFS",
    "TSYMLINK",
    "TUNLINKAT",
    "TVERSION",
    "TWALK",
    "TWRITE",
    "UNKNOWN_VERSION",
    "V9FS_MAGIC",
    "VERSION",
    "Directory",
]
