"""🔌 A cable from a network card to this machine's network.

`EthernetCable` plugs a card of the platform's into libslirp
(`socpuppet.slirp`), QEMU's user-mode network: the firmware gets an
address by DHCP, reaches this machine and what it reaches, and a port of
this machine's can be forwarded to one of the firmware's. No root is
needed. The cable is a far end the platform is pumped with:

    board.platform.build()
    with sp.EthernetCable(board.virtio.net, forward={2222: 22}) as cable:
        pump(board.platform, far_ends=[cable], until=...)

With `capture`, every frame both ways is written to a pcap file, which
Wireshark and tcpdump open: `capture="cable.pcap"`.

🎓 It stands for a cable to a switch port on a network with a router on
it, and the router is this machine. What it leaves out is what QEMU's
`-netdev user` leaves out: TCP and UDP go anywhere this machine can
reach, but nothing outside can reach in except by a forwarded port, and
ping goes beyond the gateway only where this machine lets a program ping
without root.
"""

import os
import struct
import time
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO, Protocol, Self

from socpuppet.slirp import Slirp


class NetworkCard(Protocol):
    """A card a cable plugs into: its wire, as the far end sees it."""

    def received_since(self, since: int) -> list[bytes]:
        """The frames the firmware has sent after its first `since` frames."""
        ...

    def send(self, frame: bytes) -> None:
        """Send `frame`, an Ethernet frame, to the firmware."""
        ...


class EthernetCable:
    """🔌 A cable from `card` to this machine's network, through libslirp.

    Each port of this machine's in `forward` is forwarded to the port of
    the firmware's it maps to: a program here that connects to 127.0.0.1
    at the one is connected to the firmware at the other. Close the cable,
    or use it as a context manager, to close slirp's sockets. With
    `capture`, a path, every frame both ways is written there as pcap.
    🎓 Each frame is stamped with this machine's clock when the cable
    handles it (the firmware's at a `refresh`, slirp's as it sends), not
    with simulated time: the gaps between frames are the pump's, not the
    firmware's.
    `socpuppet.errors.SlirpUnavailable` is raised where libslirp is not
    installed.
    """

    def __init__(
        self,
        card: NetworkCard,
        *,
        forward: Mapping[int, int] | None = None,
        capture: str | os.PathLike[str] | None = None,
    ) -> None:
        self._card = card
        self._taken = 0
        self._capture: _Pcap | None = None
        self._slirp = Slirp(send=self._send)
        try:
            if capture is not None:
                self._capture = _Pcap(Path(capture))
            for port, firmware_port in (forward or {}).items():
                self._slirp.forward(port, firmware_port)
        except BaseException:
            self.close()
            raise

    def fileno(self) -> int:
        """A descriptor that is readable when a socket of slirp's is ready."""
        return self._slirp.fileno()

    def due_in(self) -> float:
        """Seconds until slirp's timers are due: a second at most."""
        return self._slirp.due_in()

    def service(self) -> None:
        """Let slirp handle its sockets: what it sends goes to the card."""
        self._slirp.poll()

    def refresh(self) -> None:
        """Hand slirp what the firmware sent since the last look, and poll.

        Slirp then handles its sockets and its timers, and what it sends
        goes to the card.
        """
        sent = self._card.received_since(self._taken)
        self._taken += len(sent)
        for frame in sent:
            self._record(frame)
            self._slirp.input(frame)
        self.service()

    def close(self) -> None:
        """Unplug it: close slirp's sockets, and the capture.

        Closing it again does nothing.
        """
        self._slirp.close()
        if self._capture is not None:
            self._capture.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _send(self, frame: bytes) -> None:
        """Send `frame`, which slirp sent, to the card."""
        self._record(frame)
        self._card.send(frame)

    def _record(self, frame: bytes) -> None:
        """Write `frame` to the capture, if there is one."""
        if self._capture is not None:
            self._capture.write(frame)


class _Pcap:
    """🎓 A capture file in the classic pcap format, of Ethernet frames.

    A header for the file, then each frame after a header of its own: the
    moment, on the wall, and its length. dpkt writes one too, and is not
    among what the wheel needs, for a format this small.
    """

    def __init__(self, path: Path) -> None:
        self._file: BinaryIO = path.open("wb")
        # Magic, version 2.4, no time zone, frames whole up to 64 KiB,
        # and link type 1, Ethernet.
        self._file.write(
            struct.pack("=IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
        )

    def write(self, frame: bytes) -> None:
        seconds, nanoseconds = divmod(time.time_ns(), 1_000_000_000)
        self._file.write(
            struct.pack(
                "=IIII", seconds, nanoseconds // 1000, len(frame), len(frame)
            )
        )
        self._file.write(frame)

    def close(self) -> None:
        self._file.close()
