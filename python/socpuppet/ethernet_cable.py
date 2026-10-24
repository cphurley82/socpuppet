"""🔌 A cable from a network card to this machine's network.

`EthernetCable` plugs a card of the platform's into libslirp
(`socpuppet.slirp`), QEMU's user-mode network: the firmware gets an
address by DHCP, reaches this machine and what it reaches, and a port of
this machine's can be forwarded to one of the firmware's. No root is
needed. The cable is a far end the platform is pumped with:

    board.platform.build()
    with sp.EthernetCable(board.virtio.net, forward={2222: 22}) as cable:
        pump(board.platform, far_ends=[cable], until=...)

🎓 It stands for a cable to a switch port on a network with a router on
it, and the router is this machine. What it leaves out is what QEMU's
`-netdev user` leaves out: TCP and UDP go anywhere this machine can
reach, but nothing outside can reach in except by a forwarded port, and
ping goes beyond the gateway only where this machine lets a program ping
without root.
"""

from collections.abc import Mapping
from typing import Protocol, Self

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
    or use it as a context manager, to close slirp's sockets.
    `socpuppet.errors.SlirpUnavailable` is raised where libslirp is not
    installed.
    """

    def __init__(
        self, card: NetworkCard, *, forward: Mapping[int, int] | None = None
    ) -> None:
        self._card = card
        self._taken = 0
        self._slirp = Slirp(send=card.send)
        try:
            for port, firmware_port in (forward or {}).items():
                self._slirp.forward(port, firmware_port)
        except BaseException:
            self._slirp.close()
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
            self._slirp.input(frame)
        self.service()

    def close(self) -> None:
        """Unplug it: close slirp's sockets. Closing it again does nothing."""
        self._slirp.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
