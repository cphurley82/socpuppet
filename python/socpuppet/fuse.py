"""🧵 A directory on this machine, served over FUSE to firmware.

🎓 FUSE (Filesystem in Userspace) is Linux's protocol for a file system
served by a program instead of a driver. virtio-fs carries the same
requests from a guest to its host: each request is a header saying what to
do and to which node (a number the server hands out for each file and
directory it is asked about), then a body; each answer is a header saying
how it went, then a body. `Directory` is the program end: it answers each
request out of a real directory, as `virtiofsd` does for QEMU. 🎭 It is a
stand-in for that daemon, enough for Zephyr's and EDK2's clients, and
leaves out locks, extended attributes, links and memory mapping, which
neither asks for.

The protocol's numbers and layouts are FUSE 7.31's, which both clients
speak (`include/uapi/linux/fuse.h` in Linux).
"""

from __future__ import annotations

import errno
import os
import stat
import struct
from collections.abc import Callable
from pathlib import Path

# What a request asks for, its opcode.
LOOKUP = 1
FORGET = 2
GETATTR = 3
SETATTR = 4
MKDIR = 9
UNLINK = 10
RMDIR = 11
RENAME = 12
OPEN = 14
READ = 15
WRITE = 16
STATFS = 17
RELEASE = 18
FSYNC = 20
FLUSH = 25
INIT = 26
OPENDIR = 27
READDIR = 28
RELEASEDIR = 29
FSYNCDIR = 30
CREATE = 35
DESTROY = 38
READDIRPLUS = 44
RENAME2 = 45
LSEEK = 46

#: The protocol's version, which an INIT answer gives.
MAJOR = 7
MINOR = 31
#: INIT's flag that says directories are read with READDIRPLUS, which
#: EDK2's client asks for and will not do without.
DO_READDIRPLUS = 1 << 13
#: SETATTR's flag that says the size it carries is to be set.
FATTR_SIZE = 1 << 3

#: The top of the served directory is always node 1.
ROOT = 1
#: The most a client may write in one request, which INIT tells it.
MAX_WRITE = 1 << 16

_IN_HEADER = struct.Struct("<IIQQIIIHH")
_OUT_HEADER = struct.Struct("<IiQ")
_INIT_OUT = struct.Struct("<IIIIHHIIHHII24x")
_ATTR = struct.Struct("<QQQQQQIIIIIIIIII")
# An entry: the node, its generation, and how long the name and the
# attributes may be cached, in seconds and nanoseconds.
_ENTRY = struct.Struct("<QQQQII")
_ATTR_OUT = struct.Struct("<QII")
_OPEN_OUT = struct.Struct("<QII")
_READ_IN = struct.Struct("<QQI")
_WRITE_IN = struct.Struct("<QQIIQII")
_SETATTR_IN = struct.Struct("<IIQQQQQQIIIIIIII")
_CREATE_IN = struct.Struct("<IIII")
_LSEEK_IN = struct.Struct("<QQI")
_DIRENT = struct.Struct("<QQII")
_STATFS = struct.Struct("<QQQQQIIII24x")

#: The Linux numbers of the errors an answer can carry: a guest reads
#: Linux's, and the host Python runs on may number them otherwise
#: (macOS's ENOTEMPTY is 66).
_LINUX_ERRNO = {
    "EPERM": 1,
    "ENOENT": 2,
    "EIO": 5,
    "EBADF": 9,
    "EACCES": 13,
    "EEXIST": 17,
    "EXDEV": 18,
    "ENOTDIR": 20,
    "EISDIR": 21,
    "EINVAL": 22,
    "EFBIG": 27,
    "ENOSPC": 28,
    "ENAMETOOLONG": 36,
    "ENOSYS": 38,
    "ENOTEMPTY": 39,
    "ELOOP": 40,
}


class _Refused(Exception):
    """A request that is answered with an error, by its errno name."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def linux_errno(failure: OSError) -> int:
    """The number Linux has for the error of `failure`, or EIO's."""
    name = errno.errorcode.get(failure.errno or 0, "EIO")
    return _LINUX_ERRNO.get(name, _LINUX_ERRNO["EIO"])


class Directory:
    """🎭 Serves the directory `root` over FUSE, one request at a time.

    Call it with a request's bytes, header and body, and it gives the
    answer's bytes; a FORGET gets none, as the protocol has it. It hands
    out a node for each name it is asked about and keeps it until the name
    goes, and a file handle is the node it was opened at: each read and
    write opens the file afresh, so nothing is held open between requests.

    ⚠️ The client may change anything under `root`: create, write, rename
    and remove. Nothing outside it is reachable, by `..` or by a link that
    leads out, which is refused.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self._paths: dict[int, Path] = {ROOT: self.root}
        self._nodes: dict[Path, int] = {self.root: ROOT}
        self._next_node = ROOT + 1
        self._answers: dict[int, Callable[[int, bytes], bytes]] = {
            INIT: self._init,
            LOOKUP: self._lookup,
            GETATTR: self._getattr,
            SETATTR: self._setattr,
            MKDIR: self._mkdir,
            UNLINK: self._unlink,
            RMDIR: self._rmdir,
            RENAME: self._rename,
            RENAME2: self._rename2,
            OPEN: self._open,
            OPENDIR: self._open,
            READ: self._read,
            WRITE: self._write,
            CREATE: self._create,
            READDIR: self._readdir,
            READDIRPLUS: self._readdirplus,
            LSEEK: self._lseek,
            STATFS: self._statfs,
            RELEASE: _nothing,
            RELEASEDIR: _nothing,
            FLUSH: _nothing,
            FSYNC: _nothing,
            FSYNCDIR: _nothing,
            DESTROY: _nothing,
        }

    def __call__(self, request: bytes) -> bytes:
        """The answer to `request`, a FUSE request's bytes."""
        _, opcode, unique, node, *_ = _IN_HEADER.unpack_from(request)
        body = request[_IN_HEADER.size :]
        if opcode == FORGET:
            return b""
        answer = self._answers.get(opcode)
        try:
            if answer is None:
                raise _Refused("ENOSYS")
            return _answer(unique, 0, answer(node, body))
        except _Refused as refused:
            return _answer(unique, _LINUX_ERRNO[refused.name], b"")
        except OSError as failed:
            return _answer(unique, linux_errno(failed), b"")

    # Names and nodes.

    def _path(self, node: int) -> Path:
        if node not in self._paths:
            raise _Refused("ENOENT")
        return self._paths[node]

    def _child(self, node: int, name: bytes) -> Path:
        """Where `name` in the directory `node` is, if it is inside."""
        text = name.split(b"\0", 1)[0].decode()
        if not text or "/" in text:
            raise _Refused("EINVAL")
        parent = self._path(node)
        if text == ".":
            return parent
        if text == "..":
            return parent if parent == self.root else parent.parent
        child = parent / text
        if child.is_symlink() and not child.resolve().is_relative_to(self.root):
            raise _Refused("EACCES")
        return child

    def _node(self, path: Path) -> int:
        if path not in self._nodes:
            self._nodes[path] = self._next_node
            self._paths[self._next_node] = path
            self._next_node += 1
        return self._nodes[path]

    def _forget_path(self, path: Path) -> None:
        node = self._nodes.pop(path, None)
        if node is not None:
            del self._paths[node]

    def _attr(self, path: Path) -> bytes:
        found = path.lstat()
        return _ATTR.pack(
            self._node(path),
            found.st_size,
            found.st_blocks,
            int(found.st_atime),
            int(found.st_mtime),
            int(found.st_ctime),
            found.st_atime_ns % 1_000_000_000,
            found.st_mtime_ns % 1_000_000_000,
            found.st_ctime_ns % 1_000_000_000,
            found.st_mode,
            found.st_nlink,
            found.st_uid,
            found.st_gid,
            found.st_rdev,
            found.st_blksize,
            0,
        )

    def _entry(self, path: Path) -> bytes:
        """A name's entry: its node, and its attributes, cached for a second."""
        return _ENTRY.pack(self._node(path), 0, 1, 1, 0, 0) + self._attr(path)

    # The answers, each to a node and a request's body.

    def _init(self, _node: int, body: bytes) -> bytes:
        _, _, readahead, flags = struct.unpack_from("<IIII", body)
        return _INIT_OUT.pack(
            MAJOR, MINOR, readahead, flags & DO_READDIRPLUS, 0, 0, MAX_WRITE,
            1, 0, 0, 0, 0,
        )  # fmt: skip

    def _lookup(self, node: int, body: bytes) -> bytes:
        child = self._child(node, body)
        if not child.exists():
            raise _Refused("ENOENT")
        return self._entry(child)

    def _getattr(self, node: int, _body: bytes) -> bytes:
        return _ATTR_OUT.pack(1, 0, 0) + self._attr(self._path(node))

    def _setattr(self, node: int, body: bytes) -> bytes:
        # Only the size is set: modes, owners and times are kept as the
        # host has them, and the answer says what they are.
        path = self._path(node)
        valid, _, _, size = _SETATTR_IN.unpack_from(body)[:4]
        if valid & FATTR_SIZE:
            os.truncate(path, size)
        return _ATTR_OUT.pack(1, 0, 0) + self._attr(path)

    def _mkdir(self, node: int, body: bytes) -> bytes:
        mode, umask = struct.unpack_from("<II", body)
        child = self._child(node, body[8:])
        child.mkdir(mode=mode & ~umask & 0o7777)
        return self._entry(child)

    def _unlink(self, node: int, body: bytes) -> bytes:
        child = self._child(node, body)
        child.unlink()
        self._forget_path(child)
        return b""

    def _rmdir(self, node: int, body: bytes) -> bytes:
        child = self._child(node, body)
        child.rmdir()
        self._forget_path(child)
        return b""

    def _rename(self, node: int, body: bytes) -> bytes:
        (new_directory,) = struct.unpack_from("<Q", body)
        return self._move(node, new_directory, body[8:])

    def _rename2(self, node: int, body: bytes) -> bytes:
        new_directory, flags = struct.unpack_from("<QI", body)
        if flags:
            raise _Refused("EINVAL")
        return self._move(node, new_directory, body[16:])

    def _move(self, node: int, new_directory: int, names: bytes) -> bytes:
        old_name, new_name = names.split(b"\0")[:2]
        source = self._child(node, old_name)
        target = self._child(new_directory, new_name)
        source.rename(target)
        # Every node under the old name is under the new one now.
        for path in [p for p in self._nodes if p.is_relative_to(source)]:
            moved = target / path.relative_to(source)
            self._forget_path(moved)
            number = self._nodes.pop(path)
            self._nodes[moved] = number
            self._paths[number] = moved
        return b""

    def _open(self, node: int, _body: bytes) -> bytes:
        self._path(node)
        return _OPEN_OUT.pack(node, 0, 0)

    def _read(self, node: int, body: bytes) -> bytes:
        fh, offset, size = _READ_IN.unpack_from(body)
        with self._path(fh or node).open("rb") as file:
            file.seek(offset)
            return file.read(size)

    def _write(self, node: int, body: bytes) -> bytes:
        fh, offset, size, *_ = _WRITE_IN.unpack_from(body)
        data = body[_WRITE_IN.size : _WRITE_IN.size + size]
        with self._path(fh or node).open("r+b") as file:
            file.seek(offset)
            file.write(data)
        return struct.pack("<II", len(data), 0)

    def _create(self, node: int, body: bytes) -> bytes:
        flags, mode, umask, _ = _CREATE_IN.unpack_from(body)
        child = self._child(node, body[_CREATE_IN.size :])
        descriptor = os.open(
            child,
            os.O_CREAT
            | os.O_WRONLY
            | (flags & os.O_EXCL)
            | (flags & os.O_TRUNC),
            mode & ~umask & 0o7777,
        )
        os.close(descriptor)
        entry = self._entry(child)
        return entry + _OPEN_OUT.pack(self._node(child), 0, 0)

    def _listing(self, node: int) -> list[tuple[str, Path | None]]:
        """A directory's names, `.` and `..` first and the rest in order.

        Each comes with its path, or none for those two.
        """
        path = self._path(node)
        names = sorted(child.name for child in path.iterdir())
        return [(".", None), ("..", None)] + [(n, path / n) for n in names]

    def _readdir(self, node: int, body: bytes) -> bytes:
        return self._dirents(node, body, plus=False)

    def _readdirplus(self, node: int, body: bytes) -> bytes:
        return self._dirents(node, body, plus=True)

    def _dirents(self, node: int, body: bytes, *, plus: bool) -> bytes:
        fh, offset, size = _READ_IN.unpack_from(body)
        answer = b""
        listing = self._listing(fh or node)
        for index, (name, path) in enumerate(listing[offset:], start=offset):
            encoded = name.encode()
            kind = stat.S_IFDIR if path is None else path.lstat().st_mode
            dirent = _DIRENT.pack(
                0 if path is None else self._node(path),
                index + 1,
                len(encoded),
                stat.S_IFMT(kind) >> 12,
            ) + encoded.ljust((len(encoded) + 7) // 8 * 8, b"\0")
            if plus:
                # "." and ".." have no node of their own here: a client
                # forgets every other node it is given (EDK2 does).
                entry = (
                    bytes(_ENTRY.size + _ATTR.size)
                    if path is None
                    else self._entry(path)
                )
                dirent = entry + dirent
            if len(answer) + len(dirent) > size:
                break
            answer += dirent
        return answer

    def _lseek(self, node: int, body: bytes) -> bytes:
        fh, offset, whence = _LSEEK_IN.unpack_from(body)
        size = self._path(fh or node).stat().st_size
        if whence == os.SEEK_SET:
            place = offset
        elif whence == os.SEEK_END:
            place = size + offset
        else:
            raise _Refused("EINVAL")
        return struct.pack("<Q", place)

    def _statfs(self, _node: int, _body: bytes) -> bytes:
        found = os.statvfs(self.root)
        return _STATFS.pack(
            found.f_blocks, found.f_bfree, found.f_bavail, found.f_files,
            found.f_ffree, found.f_bsize, 255, found.f_frsize, 0,
        )  # fmt: skip


def _nothing(_node: int, _body: bytes) -> bytes:
    """The answer to a request that has nothing to do here.

    That is a release, a flush or a sync, since nothing is held open, or
    the end of a session.
    """
    return b""


def _answer(unique: int, error: int, body: bytes) -> bytes:
    return _OUT_HEADER.pack(_OUT_HEADER.size + len(body), -error, unique) + body


__all__ = ["DO_READDIRPLUS", "Directory", "linux_errno"]
