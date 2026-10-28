"""A component at its place in a platform, and its ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from socpuppet.components import Component, IdealNand, PortSpec, Router
    from socpuppet.platform import Platform


class Port:
    """One port of a described component, such as `cpu.socket`."""

    def __init__(self, placed: Placed, name: str) -> None:
        self.placed = placed
        self.name = name
        self.path = f"{placed.path}.{name}"

    @property
    def spec(self) -> PortSpec:
        """What the port is: its kind, and which way a connection goes."""
        return next(
            spec
            for spec in self.placed.component.port_specs
            if spec.name == self.name
        )


class Placed:
    """A component at its place in a platform. Its ports are attributes."""

    def __init__(
        self, platform: Platform, path: str, component: Component
    ) -> None:
        self._platform = platform
        self.path = path
        self.component = component

    def __getattr__(self, name: str) -> Port:
        # Reached only for names that are not ordinary attributes: the ports.
        if name in self.component.ports:
            return Port(self, name)
        raise AttributeError(
            f'"{self.path}" has no port called "{name}". '
            f"Its ports are: {', '.join(self.component.ports)}."
        )


class PlacedRouter(Placed):
    """A router at its place in a platform."""

    component: Router

    def map(self, target: Port, base: int, size: int | None = None) -> None:
        """Route accesses starting at `base` to the port `target`.

        The range is as long as the target component's own size, and the
        target sees addresses as offsets from `base`.

        Something with no size of its own, such as a link to another die,
        needs to be told one: `size` is then how much address space lies
        behind it.
        """
        self._platform.refuse_if_built("map a range")
        if size is None:
            size = target.placed.component.size_at(target.name)
        if size is None:
            raise ValueError(
                f"Cannot map {target.path}: it has no size of its own, as a "
                "Memory has. Say how much address space lies behind it with "
                "size=<bytes>."
            )
        output = self.component.add_output(base, size, label=target.path)
        self._platform.connect(Port(self, output), target)

    def add_input(self) -> Port:
        """Add an input, for one more source of accesses.

        The first source connects to `target`. Each one after that needs an
        input of its own: `platform.connect(device.dma, bus.add_input())`.
        Every input sees the same address map, and every input added must
        be connected.
        """
        self._platform.refuse_if_built("add an input")
        return Port(self, self.component.add_input())


class PlacedFarEnd(Placed):
    """The far end of a serial transport at its place in a platform.

    🧵 This is the other end of the line, the keyboard and screen of
    whoever sits at the console. A UART and a virtio console are two
    transports with this one far end.
    """

    @property
    def output(self) -> str:
        """Everything the firmware has printed through it so far.

        A byte that is not text comes out as the replacement character, �;
        `output_since` gives the bytes as they are.
        """
        native = self._platform.native()
        return native.far_end_output(self.path, 0).decode(errors="replace")

    def output_since(self, since: int) -> bytes:
        """What the firmware has printed after its first `since` bytes.

        As bytes, not text: `since` counts bytes and may fall inside a
        character. A terminal passes how many bytes it has shown already,
        and adds the length of what comes back.
        """
        return self._platform.native().far_end_output(self.path, since)

    def write(self, typed: str | bytes) -> None:
        """Type at it: the firmware receives `typed`.

        Text is sent as UTF-8. The bytes wait in the transport until the
        firmware takes them, and nothing happens until the platform next
        runs.

        ⚠️ They arrive all at once, with no baud rate to pace them. The
        transport loses none, and firmware that reads them into a buffer
        of its own may: Zephyr's shell keeps 64 bytes.
        """
        received = typed.encode() if isinstance(typed, str) else typed
        self._platform.native().far_end_write(self.path, received)


class PlacedGpio(Placed):
    """A GPIO block at its place in a platform, and 🧵 the far end of its pins.

    Pins are numbered 0 to 31. A pin that is not there is an IndexError.
    The platform must be built first.

    ⚠️ `level` is the GPIO's side of a pin only: what `drive` puts on a
    pin is for firmware to read, and `level` does not show it.
    """

    def level(self, pin: int) -> bool | None:
        """What the GPIO drives on `pin`: True, high; False, low; None, nothing.

        The GPIO drives nothing on a pin until firmware makes it an output.
        """
        return self._platform.native().gpio_level(self.path, pin)

    def drive(self, pin: int, level: bool | None) -> None:
        """Drive `pin` from outside: True, high; False, low; None, let go.

        Firmware reads it a delta cycle on, the next instant of the
        simulation that is at the same time. A pin let go reads high if
        firmware has its pull-up on, and low if not.
        """
        self._platform.native().gpio_drive(self.path, pin, level)

    def on_change(self, listener: Callable[[int, bool | None], object]) -> None:
        """Have `listener(pin, level)` told of each change of what a pin drives.

        Each change is told in the order it happened, a delta cycle after
        firmware made it, from the GPIO's own process: so the listener may
        `drive` a pin, which firmware reads a delta cycle after that. Each
        listener added is told, after those added before it.
        """
        self._platform.native().gpio_on_change(self.path, listener)


class PlacedUart(PlacedFarEnd):
    """A UART at its place in a platform.

    The firmware reads what is typed from its receive register, a byte at
    a time.
    """


class PlacedConsole(PlacedFarEnd):
    """🎭 A virtio console at its place in a platform.

    What is typed goes into the buffers the firmware hands it, as many
    bytes at a time as one holds.
    """


class PlacedBlock(Placed):
    """🎭 A virtio disk at its place in a platform.

    🧵 Python is the hand that puts a disk image in the drive before a run,
    and looks at what the firmware wrote to it after one.
    """

    @property
    def contents(self) -> bytes:
        """Everything on the disk, sector 0 first.

        ⚠️ All of it, as one `bytes`: the disk keeps only the sectors that
        have been written, and this is every sector, written or not.
        """
        return self._platform.native().disk_contents(self.path)

    def load(self, image: bytes) -> None:
        """Put `image` on the disk from its first sector on.

        The last sector it reaches is padded with zeros, and the rest of
        the disk is left as it was. An image larger than the disk is
        refused with a `ValueError`.
        """
        self._platform.native().disk_load(self.path, image)


class PlacedNand(Placed):
    """🎭 A NAND flash chip at its place in a platform.

    🧵 Python is the NAND programmer that puts an image in the chip before
    a run, as a factory does before the chip is soldered on, and the hand
    that reads what the firmware left in it after one.
    """

    component: IdealNand

    @property
    def contents(self) -> bytes:
        """Every page of the chip, in order, an erased page all ones.

        ⚠️ All of it, as one `bytes`: the chip keeps only the pages that
        have been programmed, and this is every page.
        """
        return self._platform.native().nand_contents(self.path)

    def load(self, image: bytes) -> None:
        """Program `image` over the chip's pages in order, from the first.

        A page the image ends part way through is filled out with ones, as
        erased, and the pages after it are left as they were. An image
        longer than the chip is refused with a `ValueError`.
        """
        self._platform.native().nand_load(self.path, image)


class PlacedPciemHost(Placed):
    """🐧 This machine as a drive's host, at its place in a platform.

    🧵 It is a far end the platform is pumped with (`socpuppet.pump`):
    the host's register writes come in on its descriptor, and at each
    look it refreshes the registers the host reads.

        board.platform.build()
        board.host.start()
        pump(board.platform, far_ends=[board.host], until=...)
    """

    def start(self) -> None:
        """Put the drive on this machine's bus, where Linux finds it.

        The registers the host reads first are refreshed before. ⚠️ The
        host's driver binds at once, and from then on the platform has to
        be pumped, or the driver waits on a drive that does not answer.
        """
        self._platform.native().pciem_host_start(self.path)

    def fileno(self) -> int:
        """The descriptor that is readable when the host has made writes."""
        return self._platform.native().pciem_host_event_fd(self.path)

    def due_in(self) -> None:
        """Nothing: everything the host does comes in on the descriptor."""
        return None

    def service(self) -> None:
        """Take the writes the host has made, to be made on the drive."""
        self._platform.native().pciem_host_service(self.path)

    def refresh(self) -> None:
        """Copy the registers the drive says into what the host reads."""
        self._platform.native().pciem_host_refresh(self.path)


class PlacedNet(Placed):
    """🎭 A virtio network device at its place in a platform.

    🧵 Python is the far end of its wire: whatever is on the other side of
    the network, a switch, a server, or a test that answers.
    """

    @property
    def received(self) -> list[bytes]:
        """Every frame the firmware has sent, in the order it sent them.

        Each is without the virtio header in front of it, so it starts with
        its Ethernet header.
        """
        return self.received_since(0)

    def received_since(self, since: int) -> list[bytes]:
        """The frames the firmware has sent after its first `since` frames.

        A far end that keeps up with the wire passes how many frames it has
        taken already, and adds how many come back.
        """
        return self._platform.native().net_received(self.path, since)

    def send(self, frame: bytes) -> None:
        """Send `frame`, an Ethernet frame, to the firmware.

        It waits in the device until the firmware holds out a buffer, and
        nothing happens until the platform next runs. A frame longer than
        that buffer is dropped, and counted in `dropped`.
        """
        self._platform.native().net_send(self.path, frame)

    @property
    def dropped(self) -> int:
        """How many frames sent to the firmware were dropped.

        A frame is dropped when it is longer than the buffer the firmware
        held out for it.
        """
        return self._platform.native().net_dropped(self.path)
