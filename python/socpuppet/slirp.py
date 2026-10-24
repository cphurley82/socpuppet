"""🔌 libslirp, the network of QEMU's `-netdev user`, from Python.

libslirp is a TCP/IP stack in a library. To a guest it is a router on
its wire, with a DHCP server and a DNS relay behind it; on this machine
it is a program like any other, opening sockets of its own for whatever
the guest connects to. So a guest gets this machine's network with no
root, no bridge and no TAP device.

🎓 The structures and calls are spelled out here, once, as libslirp's
header has them: this module is the one place socpuppet knows its C ABI.
"""

import ctypes
import ipaddress
import selectors
import sys
import time
from collections.abc import Callable
from ctypes.util import find_library
from typing import Self

from socpuppet.errors import SlirpUnavailable

#: The guest's network, as QEMU's user-mode network has it.
NETWORK = ipaddress.IPv4Network("10.0.2.0/24")
#: The guest's gateway, which is this machine as the guest sees it: what
#: the guest sends there goes to this machine's 127.0.0.1.
GATEWAY = ipaddress.IPv4Address("10.0.2.2")
#: The DNS relay, which asks this machine's own resolver.
NAMESERVER = ipaddress.IPv4Address("10.0.2.3")
#: The first address the DHCP server gives out, and the guest's.
GUEST = ipaddress.IPv4Address("10.0.2.15")
#: Where a forwarded port listens: this machine alone can connect.
LOOPBACK = ipaddress.IPv4Address("127.0.0.1")


class Slirp:
    """🔌 A network for one guest, with this machine's sockets behind it.

    What the guest sends goes in by `input`, and what slirp sends the guest
    comes out by the `send` it was made with, at once or at a `poll`.
    `fileno` and `due_in` say when to poll next. Close it, or use it as a
    context manager, to close its sockets.
    """

    def __init__(self, *, send: Callable[[bytes], None]) -> None:
        self._library = _load()
        self._send = send
        # ⚠️ Kept for as long as slirp is: slirp keeps the pointer to the
        # callbacks, and calls them.
        self._callbacks = _Callbacks(
            send_packet=_SendPacket(self._send_packet),
            clock_get_ns=_ClockGetNs(lambda _: time.monotonic_ns()),
            register_poll_fd=_PollFd(lambda fd, _: None),
            unregister_poll_fd=_PollFd(lambda fd, _: None),
            notify=_Notify(lambda _: None),
        )
        config = _Config(
            version=1,
            in_enabled=True,
            vnetwork=_in_addr(NETWORK.network_address),
            vnetmask=_in_addr(NETWORK.netmask),
            vhost=_in_addr(GATEWAY),
            vdhcp_start=_in_addr(GUEST),
            vnameserver=_in_addr(NAMESERVER),
        )
        self._slirp: int | None = self._library.slirp_new(
            ctypes.byref(config), ctypes.byref(self._callbacks), None
        )
        # Its sockets, each with what slirp waits for of it, in the order
        # slirp numbers them.
        self._selector = selectors.DefaultSelector()
        self._waited_on: list[tuple[int, int]] = []
        self._within = 0.0
        self._wait_again()

    def input(self, frame: bytes) -> None:
        """Take `frame`, an Ethernet frame the guest sent."""
        self._library.slirp_input(self._slirp, frame, len(frame))

    def forward(self, port: int, guest_port: int) -> None:
        """Forward TCP `port` of this machine's to `guest_port` of the guest's.

        A program here that connects to 127.0.0.1 at `port` is connected to
        the guest at `guest_port`. Only this machine can connect: the port
        is listened on at 127.0.0.1 alone. A port that cannot be listened
        on, such as one that is taken, is refused with an `OSError`.
        """
        if self._library.slirp_add_hostfwd(
            self._slirp,
            0,
            _in_addr(LOOPBACK),
            port,
            _in_addr(GUEST),
            guest_port,
        ):
            raise OSError(
                f"port {port} of this machine's could not be listened on: "
                "is it taken?"
            )
        self._wait_again()

    def fileno(self) -> int:
        """A descriptor that is readable when a socket of slirp's is ready.

        Ready for what slirp waits for of it, as of the last `poll`.
        """
        return self._selector.fileno()

    def due_in(self) -> float:
        """Seconds on the wall until slirp is to be polled again at most.

        As of the last `poll`. It is never more than a second, and is half
        that while a TCP connection is open, and less while one of TCP's
        timers is running, such as a delayed acknowledgement's.
        """
        return self._within

    def poll(self, seconds: float = 0) -> None:
        """Wait up to `seconds` for slirp's sockets, then let it handle them.

        It waits no longer than `due_in`. Slirp then reads and writes the
        sockets that are ready, sends the guest what it has for it, and
        does what its timers say is due.
        """
        self._wait_again()
        ready = {
            key.fd: events
            for key, events in self._selector.select(min(seconds, self._within))
        }
        happened = [_poll_events(ready.get(fd, 0)) for fd, _ in self._waited_on]
        self._library.slirp_pollfds_poll(
            self._slirp, 0, _GetRevents(lambda at, _: happened[at]), None
        )
        self._wait_again()

    def close(self) -> None:
        """Close its sockets, and everything else of slirp's.

        Closing it again does nothing.
        """
        if self._slirp is not None:
            self._library.slirp_cleanup(self._slirp)
            self._slirp = None
            self._selector.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _wait_again(self) -> None:
        """Ask slirp what it waits for now, and wait on just that."""
        waited_on: list[tuple[int, int]] = []

        def add(fd: int, events: int, _: int) -> int:
            waited_on.append((fd, events))
            return len(waited_on) - 1

        milliseconds = ctypes.c_uint32(0xFFFF_FFFF)
        self._library.slirp_pollfds_fill(
            self._slirp, ctypes.byref(milliseconds), _AddPoll(add), None
        )
        # ⚠️ Afresh each time: slirp may have closed a socket, and opened
        # another with the same descriptor.
        for key in list(self._selector.get_map().values()):
            self._selector.unregister(key.fd)
        for fd, events in waited_on:
            self._selector.register(fd, _selector_events(events))
        self._waited_on = waited_on
        self._within = milliseconds.value / 1000

    def _send_packet(self, frame: int, length: int, _: int) -> int:
        self._send(ctypes.string_at(frame, length))
        return length


def version() -> str:
    """The version of the libslirp that is installed, such as 4.9.1."""
    said: bytes = _load().slirp_version_string()
    return said.decode()


def places() -> list[str]:
    """Where libslirp is looked for, in order.

    Where this machine says it is, then where Homebrew puts it on an
    Apple silicon Mac, which is not a place a Mac looks for libraries.
    """
    found = find_library("slirp")
    return [
        *([found] if found is not None else []),
        "/opt/homebrew/lib/libslirp.0.dylib",
    ]


def _load() -> ctypes.CDLL:
    """The libslirp that is installed, or `SlirpUnavailable`."""
    for path in places():
        try:
            return _declared(ctypes.CDLL(path))
        except OSError:
            pass
    raise SlirpUnavailable(
        "🩺 libslirp is not installed, and it is what plugs a network "
        "card into this machine's network. Install it with "
        "sudo apt-get install -y libslirp-dev, or brew install libslirp "
        "(uv run python tools/doctor.py cable checks)."
    )


# 🎓 libslirp's header, as far as socpuppet uses it. Its configuration is
# of version 1, which every libslirp has, with IPv6 off. Then slirp makes
# no timer of its own (the one it has is for IPv6), and reports no error
# of the guest's (each is IPv6's): those callbacks are left out, NULL.

_SendPacket = ctypes.CFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p
)
_ClockGetNs = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_void_p)
_PollFd = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_void_p)
_Notify = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
_AddPoll = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p
)
_GetRevents = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_void_p)


class _Callbacks(ctypes.Structure):
    """`SlirpCb`, as far as version 1 of the configuration."""

    _fields_ = [
        ("send_packet", _SendPacket),
        ("guest_error", ctypes.c_void_p),
        ("clock_get_ns", _ClockGetNs),
        ("timer_new", ctypes.c_void_p),
        ("timer_free", ctypes.c_void_p),
        ("timer_mod", ctypes.c_void_p),
        ("register_poll_fd", _PollFd),
        ("unregister_poll_fd", _PollFd),
        ("notify", _Notify),
    ]


class _InAddr(ctypes.Structure):
    """`struct in_addr`: an IPv4 address, in the network's byte order."""

    _fields_ = [("s_addr", ctypes.c_uint32)]


class _In6Addr(ctypes.Structure):
    """`struct in6_addr`, which is never more than zeros here."""

    _fields_ = [("s6_addr32", ctypes.c_uint32 * 4)]


class _Config(ctypes.Structure):
    """`SlirpConfig`, as far as version 1."""

    _fields_ = [
        ("version", ctypes.c_uint32),
        ("restricted", ctypes.c_int),
        ("in_enabled", ctypes.c_bool),
        ("vnetwork", _InAddr),
        ("vnetmask", _InAddr),
        ("vhost", _InAddr),
        ("in6_enabled", ctypes.c_bool),
        ("vprefix_addr6", _In6Addr),
        ("vprefix_len", ctypes.c_uint8),
        ("vhost6", _In6Addr),
        ("vhostname", ctypes.c_char_p),
        ("tftp_server_name", ctypes.c_char_p),
        ("tftp_path", ctypes.c_char_p),
        ("bootfile", ctypes.c_char_p),
        ("vdhcp_start", _InAddr),
        ("vnameserver", _InAddr),
        ("vnameserver6", _In6Addr),
        ("vdnssearch", ctypes.POINTER(ctypes.c_char_p)),
        ("vdomainname", ctypes.c_char_p),
        ("if_mtu", ctypes.c_size_t),
        ("if_mru", ctypes.c_size_t),
        ("disable_host_loopback", ctypes.c_bool),
        ("enable_emu", ctypes.c_bool),
    ]


def _in_addr(address: ipaddress.IPv4Address) -> _InAddr:
    """`address` as a `struct in_addr`: its bytes in the network's order."""
    return _InAddr(int.from_bytes(address.packed, sys.byteorder))


#: That a socket is to be read, and to be written: slirp's `SLIRP_POLL_IN`
#: and `SLIRP_POLL_OUT`.
_POLL_IN = 1 << 0
_POLL_OUT = 1 << 1


def _selector_events(events: int) -> int:
    """What slirp waits for of a socket, as a selector's events."""
    return (selectors.EVENT_READ if events & _POLL_IN else 0) | (
        selectors.EVENT_WRITE if events & _POLL_OUT else 0
    )


def _poll_events(events: int) -> int:
    """What a selector says of a socket, as slirp's events."""
    return (_POLL_IN if events & selectors.EVENT_READ else 0) | (
        _POLL_OUT if events & selectors.EVENT_WRITE else 0
    )


def _declared(library: ctypes.CDLL) -> ctypes.CDLL:
    """`library`, with the arguments and results of its calls declared."""
    library.slirp_version_string.restype = ctypes.c_char_p
    library.slirp_new.restype = ctypes.c_void_p
    library.slirp_new.argtypes = [
        ctypes.POINTER(_Config),
        ctypes.POINTER(_Callbacks),
        ctypes.c_void_p,
    ]
    library.slirp_input.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.slirp_cleanup.argtypes = [ctypes.c_void_p]
    library.slirp_add_hostfwd.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        _InAddr,
        ctypes.c_int,
        _InAddr,
        ctypes.c_int,
    ]
    library.slirp_pollfds_fill.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        _AddPoll,
        ctypes.c_void_p,
    ]
    library.slirp_pollfds_poll.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        _GetRevents,
        ctypes.c_void_p,
    ]
    return library
