"""Describe a platform in Python, then build and run it."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, NamedTuple, Protocol

from socpuppet import address_map, devicetree, interrupt_map
from socpuppet.address_map import MapEntry, reachable_ports
from socpuppet.components import LinkModel
from socpuppet.interrupt_map import InterruptEntry
from socpuppet.placed import Placed, Port
from socpuppet.terminal import stdout_wants_color
from socpuppet.time import us
from socpuppet.trace import TraceRecord

if TYPE_CHECKING:
    from socpuppet import _core


class Placeable[P: Placed](Protocol):
    """What can be added to a platform: anything that can take its place.

    Every `Component` can. What `place` returns is what `add` hands back,
    so a router's `add` gives a `PlacedRouter`, with `map` on it.
    """

    def place(self, platform: Platform, path: str) -> P:
        """The component at `path` in `platform`."""
        ...


class Link:
    """A link placed between two dies: endpoint `a` on one, `b` on the other.

    Send traffic into `a.target` and it comes out of `b.initiator`, and the
    same from `b` to `a`.
    """

    def __init__(self, a: Placed, b: Placed) -> None:
        self.a = a
        self.b = b


class Connection(NamedTuple):
    """A source port connected to a sink port.

    `trace` says whether to record what crosses.
    """

    source: Port
    sink: Port
    trace: bool = False


class Group:
    """A level of naming, such as a die.

    Components added here get its path as a prefix.
    """

    def __init__(self, platform: Platform, path: str) -> None:
        self._platform = platform
        self.path = path

    def add[P: Placed](self, name: str, component: Placeable[P]) -> P:
        """Place `component` inside this group and return it with its ports."""
        return self._platform.add(f"{self.path}.{name}", component)

    def group(self, name: str) -> Group:
        """A group nested inside this one."""
        return self._platform.group(f"{self.path}.{name}")


class Platform:
    """A platform description, and once built, the running simulation.

    Describe first (`add`, `connect`), then `build()`, then `run()`.
    Describing needs only Python; the simulator is loaded by `build()`.
    """

    def __init__(self) -> None:
        self._placed: dict[str, Placed] = {}
        self._connections: list[Connection] = []
        # The groups by path, and each link as (name, endpoint a, endpoint
        # b), both in the order they were described.
        self._groups: list[str] = []
        self._links: list[tuple[str, str, str]] = []
        self._quantum = us(100)
        self._native: _core.Platform | None = None

    @property
    def quantum(self) -> int:
        """How far a CPU may run ahead of simulated time (see `ns`, `us`).

        🎓 A CPU model is fast because it executes many instructions in one
        go, and only then lets the rest of the platform catch up. The
        quantum is the limit on that running ahead. A longer one is
        faster. A shorter one means the others see what the CPU did, and
        the CPU sees an interrupt, with less delay. Zero means no running
        ahead at all. Set it before `build()`.

        The default is 100 µs. On a loop of two million instructions the
        CPU ran five times faster with it than with none, and no faster
        with more. It is 1% of the 10 ms tick most firmware keeps time by.
        """
        return self._quantum

    @quantum.setter
    def quantum(self, picoseconds: int) -> None:
        self.refuse_if_built("change the quantum")
        self._quantum = picoseconds

    def add[P: Placed](self, path: str, component: Placeable[P]) -> P:
        """Place `component` at `path` and return it with its ports."""
        self.refuse_if_built("add a component")
        if path in self._placed:
            raise ValueError(
                f'There is already a component called "{path}". '
                "Each component needs its own name."
            )
        placed = component.place(self, path)
        self._placed[path] = placed
        return placed

    def group(self, name: str) -> Group:
        """A named group of components, such as a die."""
        if name not in self._groups:
            self._groups.append(name)
        return Group(self, name)

    def link(
        self,
        name: str,
        model: LinkModel,
        a: Group | None = None,
        b: Group | None = None,
        trace: bool = False,
    ) -> Link:
        """Place a link called `name` between group `a` and group `b`.

        Each group gets one endpoint. `model` says which link to use, such
        as `D2dLink()` or 🎭 `PassThroughLink()`. The endpoints are named
        `<group>.<name>`; with no groups given they are `<name>.a` and
        `<name>.b`.

        With `trace=True`, everything that crosses the link is recorded,
        each path of it separately: a link with a sideband of its own shows
        its management traffic apart from the dies' (see `trace`).
        """
        path_a = f"{a.path}.{name}" if a is not None else f"{name}.a"
        path_b = f"{b.path}.{name}" if b is not None else f"{name}.b"
        end_a = self.add(path_a, model.endpoint())
        end_b = self.add(path_b, model.endpoint())
        for source, sink in model.peer_pairs():
            self.connect(getattr(end_a, source), getattr(end_b, sink), trace)
            self.connect(getattr(end_b, source), getattr(end_a, sink), trace)
        self._links.append((name, path_a, path_b))
        return Link(end_a, end_b)

    def connect(self, source: Port, sink: Port, trace: bool = False) -> None:
        """Connect a source port (an initiator) to a sink port (a target).

        With `trace=True`, every transaction crossing the connection is
        recorded (see `trace`). ⚠️ A traced connection refuses direct memory
        access, because an access that bypasses the bus would bypass the
        trace as well.
        """
        self.refuse_if_built("connect ports")
        _refuse_a_mismatch(source, sink, trace)
        _refuse_a_second_connection(self._connections, source, sink)
        self._connections.append(Connection(source, sink, trace))

    def build(self) -> None:
        """Create the simulation from the description."""
        self.refuse_if_built("build it again")
        # Anything wrong with the description comes out here, before the
        # simulator is created, because a process gets only one of those.
        parameters = {
            path: self._parameters_of(placed)
            for path, placed in self._placed.items()
        }
        from socpuppet import _core  # the simulator loads here, not on import

        native = _core.Platform(color_log=stdout_wants_color())
        native.set_quantum(self._quantum)
        for path, placed in self._placed.items():
            native.add(path, placed.component.implementation, parameters[path])
            placed.component.configure(native, path)
        for source, sink, trace in self._connections:
            native.bind(source.path, sink.path, trace)
        native.elaborate()
        self._native = native

    def run(self, duration: int | None = None) -> None:
        """Run for `duration`, or until nothing is left to do.

        For durations, see `ns` and `us`.
        """
        if duration is None:
            self.native().run()
        else:
            self.native().run_for(duration)

    def step(self) -> bool:
        """Move to the next moment anything is scheduled for, and let it happen.

        Returns False if nothing was left to do.
        """
        return self.native().step()

    def run_until(
        self, condition: Callable[[], bool], timeout: int | None = None
    ) -> bool:
        """Run until `condition()` is true, and say whether it came true.

        The condition is checked each time simulated time is about to move
        on, once everything that happens at that moment has happened. The
        run also ends when nothing is left to do, or when `timeout` (see
        `ns`, `us`) has passed.
        """
        native = self.native()
        deadline = None if timeout is None else self.time + timeout
        while True:
            # Asking what comes next lets everything that happens at this
            # moment happen first, so the condition is looked at with the
            # moment settled, and before the clock leaves it.
            ahead = native.picoseconds_to_next_activity()
            if condition():
                return True
            if ahead is None:
                return False  # nothing left to do
            if deadline is not None and self.time + ahead > deadline:
                native.run_for(deadline - self.time)
                return False  # out of time, and nothing happened in it
            native.step()

    @property
    def trace(self) -> list[TraceRecord]:
        """Every transaction recorded on traced connections, oldest first."""
        return [
            TraceRecord.from_native(native)
            for native in self.native().trace_records()
        ]

    @property
    def time(self) -> int:
        """The simulated time now, in the unit `ns` and `us` return."""
        return self.native().time_in_picoseconds()

    def peek32(self, address: int, via: Port | None = None) -> int:
        """Read a 32-bit little-endian value, as a bus master sees memory.

        `via` is the master's port to look through, such as `cpu.socket`. It
        may be left out when the platform has exactly one bus master.

        A peek takes no simulated time and nothing in the platform notices
        it, the way a debugger reads memory.
        """
        return int.from_bytes(self.peek(address, 4, via), "little")

    def peek(self, address: int, length: int, via: Port | None = None) -> bytes:
        """Read `length` bytes from `address` on, as a bus master sees memory.

        Like `peek32`, it takes no simulated time, and `via` works the same.
        """
        view = self._view(via)
        data = self.native().debug_read(view.path, address, length)
        if data is None:
            raise self._nothing_at(address, length, view)
        return data

    def poke32(self, address: int, value: int, via: Port | None = None) -> None:
        """Write a 32-bit little-endian value, as a bus master sees memory.

        Like a peek, a poke takes no simulated time. `via` works as in `peek32`.
        """
        self.poke(address, value.to_bytes(4, "little"), via)

    def poke(self, address: int, data: bytes, via: Port | None = None) -> None:
        """Write `data` starting at `address`, as a bus master sees memory.

        This is how a program gets into memory before the CPU runs it. Like
        a peek, a poke takes no simulated time. `via` works as in `peek32`.
        """
        view = self._view(via)
        if not self.native().debug_write(view.path, address, data):
            raise self._nothing_at(address, len(data), view)

    def load_elf(
        self, path: str | os.PathLike[str], via: Port | None = None
    ) -> None:
        """Put the program in the ELF file at `path` into memory.

        🎓 An ELF file is what a linker produces: the program's bytes in
        segments, each with the address it belongs at. Loading writes each
        segment to its address, as `poke` would. `via` works as in `peek32`.

        The CPU the image is loaded through may refuse it. A CPU runs only
        programs built for its own word size, and it starts executing at a
        fixed address, its reset vector, so an image that starts anywhere
        else would never run.
        """
        view = self._view(via)
        self.native()  # refuse if there is no memory to load into yet
        file = os.fspath(path)
        # The reader cannot tell a missing file from one that is not ELF.
        if not os.path.exists(file):
            raise FileNotFoundError(
                f"There is no file at {file}. Build the firmware first, or "
                "check the path."
            )
        from socpuppet import _core  # the simulator is loaded by now

        xlen, entry, segments = _core.read_elf(file)
        view.placed.component.refuse_image(
            image=file, xlen=xlen, entry=entry, path=view.placed.path
        )
        for address, data in segments:
            try:
                self.poke(address, data, view)
            except LookupError as nothing_there:
                raise LookupError(
                    f"{file} has {len(data)} bytes to load at {address:#x}, "
                    f"and no memory takes all of them, as seen from "
                    f"{view.path}. Check the firmware's memory layout "
                    "against the platform's: where the RAM starts and how "
                    "big it is."
                ) from nothing_there

    def devicetree(self, via: Port | None = None) -> str:
        """The devicetree source for what a bus master can reach.

        `via` is the master's port, as in `peek32`. Works on a description;
        nothing needs to be built.
        """
        return devicetree.generate(self._connections, self._view(via))

    def devicetree_overlay(
        self, only: Collection[Placed], via: Port | None = None
    ) -> str:
        """The devicetree source for some components, as an overlay.

        An overlay adds to a devicetree that firmware already has. This one
        has the nodes of the components `only`, for a devicetree that
        describes the rest of what the master at `via` can reach.
        """
        return devicetree.overlay(self._connections, self._view(via), only)

    def address_map(self, via: Port | None = None) -> list[MapEntry]:
        """What a bus master can reach, and at which address.

        One entry for each port that answers accesses, lowest address
        first. `via` is the master's port, as in `peek32`. Works on a
        description; nothing needs to be built.
        """
        return address_map.entries(
            self._connections, self._view(via), self._groups
        )

    def address_maps(self) -> dict[str, list[MapEntry]]:
        """The address map of each bus master, by the path of its socket."""
        return {
            master.socket.path: self.address_map(master.socket)
            for master in self.bus_masters
        }

    def interrupt_map(self) -> list[InterruptEntry]:
        """Whose interrupt line is which number, to the firmware.

        One entry for each line that goes to a numbered input of an
        interrupt controller or of a CPU, in order of controller and then
        of number. Works on a description; nothing needs to be built.
        """
        return interrupt_map.entries(self._connections)

    def to_json(self) -> str:
        """The description as JSON.

        Every component and every connection, the groups, which two
        endpoints make each link, and the quantum (in the unit `ns` and
        `us` return). Then what follows from those: the address map of
        each bus master, by the path of its socket (see `address_map`),
        and the interrupt map (see `interrupt_map`).

        A scripted bus master's script is behavior, not structure, and is
        left out. A component's parameters include what it works out from
        the description, so a description that does not yet say enough for
        that is refused, as it would be by `build()`. So is one whose
        address map leads back to where it has been, which has no end to
        write down.
        """
        return json.dumps(
            {
                "components": {
                    path: {
                        "implementation": placed.component.implementation,
                        "parameters": self._parameters_of(placed),
                    }
                    for path, placed in self._placed.items()
                },
                "connections": [
                    {"source": source.path, "sink": sink.path, "trace": trace}
                    for source, sink, trace in self._connections
                ],
                "groups": self._groups,
                "links": [
                    {"name": name, "a": a, "b": b} for name, a, b in self._links
                ],
                "quantum": self._quantum,
                "address_maps": {
                    view: [entry.as_json() for entry in entries]
                    for view, entries in self.address_maps().items()
                },
                "interrupts": [
                    entry.as_json() for entry in self.interrupt_map()
                ],
            },
            indent=2,
        )

    def _nothing_at(self, address: int, length: int, view: Port) -> LookupError:
        return LookupError(
            f"Nothing took a {length}-byte access at address {address:#x}, "
            f"as seen from {view.path}. The whole access has to fit inside "
            "one entry of the memory map: check the address, and that the "
            "access does not run past the end of what is there."
        )

    def _parameters_of(self, placed: Placed) -> dict[str, int]:
        """What a component is configured with.

        That is what it was told, and what it works out from where it is in
        the description.
        """

        def address_of(port: str) -> int | None:
            return self._address_of(Port(placed, port))

        return placed.component.parameters | (
            placed.component.located_parameters(placed.path, address_of)
        )

    def _address_of(self, port: Port) -> int | None:
        """Where the bus masters find `port`, or None if none can reach it.

        Raises if two of them find it at different addresses, since there
        is then no one answer.
        """
        views = {
            placed.socket.path: found.address
            for placed in self.bus_masters
            for found in reachable_ports(self._connections, placed.socket)
            if found.port.path == port.path
        }
        if len(set(views.values())) > 1:
            seen = ", ".join(
                f"{address:#x} from {master}"
                for master, address in views.items()
            )
            raise ValueError(
                f"The bus masters of this platform find {port.path} at "
                f"different addresses: {seen}. Its component needs one "
                "address to go by, so only one master's view can lead to it."
            )
        return next(iter(views.values()), None)

    def _view(self, via: Port | None) -> Port:
        """The port a peek or poke looks through."""
        if via is not None:
            return via
        masters = self.bus_masters
        if len(masters) != 1:
            raise ValueError(
                f"This platform has {len(masters)} bus masters, so say whose "
                "view of memory you want: pass via=<a master's port>, such as "
                "via=cpu.socket."
            )
        return masters[0].socket

    @property
    def bus_masters(self) -> list[Placed]:
        """The components whose view of memory a peek or a devicetree takes.

        They are the CPUs and their stand-ins, in the order they were added.
        """
        return [
            placed
            for placed in self._placed.values()
            if placed.component.is_bus_master
        ]

    def port(self, path: str) -> Port:
        """The port at a path, such as `"io.ram.socket"`.

        The path is the component's own, a dot, and the port's name. This
        is for a caller that has only names to go by, such as a command
        line. With the placed component in hand, `ram.socket` is the same
        port.
        """
        component, _, name = path.rpartition(".")
        placed = self._placed.get(component)
        if placed is None:
            raise ValueError(
                f'"{path}" names no port: there is no component called '
                f'"{component}". The components are: '
                f"{', '.join(self._placed)}."
            )
        if name not in placed.component.ports:
            raise ValueError(
                f'"{path}" names no port: "{component}" has no port called '
                f'"{name}". Its ports are: '
                f"{', '.join(placed.component.ports)}."
            )
        return Port(placed, name)

    def refuse_if_built(self, change: str) -> None:
        """Raise if the platform is built, since its topology is then fixed."""
        if self._native is not None:
            raise RuntimeError(
                f"Cannot {change}: this platform is already built. SystemC "
                "fixes the topology once the simulation is created, so "
                "describe everything before calling build()."
            )

    def native(self) -> _core.Platform:
        """The simulator underneath, once `build()` has created it.

        For placed components such as `PlacedUart`. A platform's users have
        `run`, `peek32` and the rest.
        """
        if self._native is None:
            raise RuntimeError(
                "This platform is only described so far. Call build() first "
                "to create the simulation."
            )
        return self._native


def _refuse_a_mismatch(source: Port, sink: Port, trace: bool) -> None:
    """Raise if the two ports cannot be connected, or not with a trace.

    The simulator would refuse the same at `build()`. Refusing here means
    that everything made from a description (a devicetree, the JSON) is
    made from one that can be built.
    """
    first, second = source.spec, sink.spec
    if first.kind != second.kind:
        raise ValueError(
            f"Cannot connect {source.path} to {sink.path}: the first is a "
            f"{first.kind} port and the second is a {second.kind} port."
        )
    if first.role != "source" or second.role != "sink":
        raise ValueError(
            f"Cannot connect {source.path} to {sink.path}: the first must be "
            "a source (a bus master's socket, or the port driving a wire) "
            "and the second a sink (a target's socket, or a port reading a "
            "wire)."
        )
    if trace and first.kind != "bus":
        raise ValueError(
            f"Cannot trace the connection from {source.path} to "
            f"{sink.path}: only a bus connection can be traced, and this is "
            "a wire."
        )


def _refuse_a_second_connection(
    connections: list[Connection], source: Port, sink: Port
) -> None:
    """Raise if either port has the one connection it can take.

    The exception is the port that drives a wire, which any number of
    inputs may read.
    """
    for each in connections:
        if each.sink.path == sink.path:
            raise ValueError(
                f"{sink.path} is already connected to {each.source.path}. "
                + (
                    "A socket takes accesses from one place: give each "
                    "further source an input of a router, with add_input()."
                    if sink.spec.kind == "bus"
                    else "A wire input has one driver."
                )
            )
        if source.spec.kind == "bus" and each.source.path == source.path:
            raise ValueError(
                f"{source.path} is already connected to {each.sink.path}. "
                "A socket's accesses go to one place: to reach several "
                "targets, connect it to a router (sp.Router) and map each "
                "target onto that."
            )
