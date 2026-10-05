"""Describe a platform in Python, then build and run it."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple, overload

from socpuppet import devicetree
from socpuppet.components import (
    Component,
    LinkModel,
    Router,
)
from socpuppet.trace import TraceRecord, wants_color

if TYPE_CHECKING:
    from socpuppet import _core


class Port:
    """One port of a described component, such as `cpu.socket`."""

    def __init__(self, placed: Placed, name: str) -> None:
        self.placed = placed
        self.name = name
        self.path = f"{placed.path}.{name}"


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

    def map(self, target: Port, base: int) -> None:
        """Route accesses starting at `base` to the port `target`.

        The range is as long as the target component's own size, and the
        target sees addresses as offsets from `base`.
        """
        self._platform.refuse_if_built("map a range")
        size = target.placed.component.parameters.get("size")
        if size is None:
            raise ValueError(
                f"Cannot map {target.path}: only a component with a size of "
                "its own, such as a Memory, can be mapped onto a router."
            )
        output = self.component.add_output(base, size, label=target.path)
        self._platform.connect(Port(self, output), target)


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

    @overload
    def add(self, name: str, component: Router) -> PlacedRouter: ...
    @overload
    def add(self, name: str, component: Component) -> Placed: ...
    def add(self, name: str, component: Component) -> Placed:
        """Place `component` inside this group and return it with its ports."""
        return self._platform.add(f"{self.path}.{name}", component)

    def group(self, name: str) -> Group:
        """A group nested inside this one."""
        return Group(self._platform, f"{self.path}.{name}")


class Platform:
    """A platform description, and once built, the running simulation.

    Describe first (`add`, `connect`), then `build()`, then `run()`.
    Describing needs only Python; the simulator is loaded by `build()`.
    """

    def __init__(self) -> None:
        self._placed: dict[str, Placed] = {}
        self._connections: list[Connection] = []
        self._native: _core.Platform | None = None

    @overload
    def add(self, path: str, component: Router) -> PlacedRouter: ...
    @overload
    def add(self, path: str, component: Component) -> Placed: ...
    def add(self, path: str, component: Component) -> Placed:
        """Place `component` at `path` and return it with its ports."""
        self.refuse_if_built("add a component")
        if path in self._placed:
            raise ValueError(
                f'There is already a component called "{path}". '
                "Each component needs its own name."
            )
        placed_type = PlacedRouter if isinstance(component, Router) else Placed
        placed = placed_type(self, path, component)
        self._placed[path] = placed
        return placed

    def group(self, name: str) -> Group:
        """A named group of components, such as a die."""
        return Group(self, name)

    def link(
        self,
        name: str,
        model: LinkModel,
        a: Group | None = None,
        b: Group | None = None,
    ) -> Link:
        """Place a link called `name` between group `a` and group `b`.

        Each group gets one endpoint. `model` says which link to use, such
        as `PassThroughLink()`. The endpoints are named `<group>.<name>`;
        with no groups given they are `<name>.a` and `<name>.b`.
        """
        path_a = f"{a.path}.{name}" if a is not None else f"{name}.a"
        path_b = f"{b.path}.{name}" if b is not None else f"{name}.b"
        end_a = self.add(path_a, model.endpoint())
        end_b = self.add(path_b, model.endpoint())
        self.connect(end_a.peer_initiator, end_b.peer_target)
        self.connect(end_b.peer_initiator, end_a.peer_target)
        return Link(end_a, end_b)

    def connect(self, source: Port, sink: Port, trace: bool = False) -> None:
        """Connect a source port (an initiator) to a sink port (a target).

        With `trace=True`, every transaction crossing the connection is
        recorded (see `trace`). ⚠️ A traced connection refuses direct memory
        access, because an access that bypasses the bus would bypass the
        trace as well.
        """
        self.refuse_if_built("connect ports")
        self._connections.append(Connection(source, sink, trace))

    def build(self) -> None:
        """Create the simulation from the description."""
        self.refuse_if_built("build it again")
        from socpuppet import _core  # the simulator loads here, not on import

        native = _core.Platform(
            color_log=wants_color(sys.stdout.isatty(), os.environ)
        )
        for path, placed in self._placed.items():
            native.add(
                path,
                placed.component.implementation,
                placed.component.parameters,
            )
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
            self._built().run()
        else:
            self._built().run_for(duration)

    def step(self) -> bool:
        """Move to the next moment anything is scheduled for, and let it happen.

        Returns False if nothing was left to do.
        """
        return self._built().step()

    def run_until(
        self, condition: Callable[[], bool], timeout: int | None = None
    ) -> bool:
        """Run until `condition()` is true, and say whether it came true.

        The condition is checked each time simulated time is about to move
        on. The run also ends when nothing is left to do, or when `timeout`
        (see `ns`, `us`) has passed.
        """
        native = self._built()
        deadline = None if timeout is None else self.time + timeout
        while not condition():
            ahead = native.picoseconds_to_next_activity()
            if ahead is None:
                return False  # nothing left to do
            if deadline is not None and self.time + ahead > deadline:
                native.run_for(deadline - self.time)
                return condition()
            native.step()
        return True

    @property
    def trace(self) -> list[TraceRecord]:
        """Every transaction recorded on traced connections, oldest first."""
        return [
            TraceRecord.from_native(native)
            for native in self._built().trace_records()
        ]

    @property
    def time(self) -> int:
        """The simulated time now, in the unit `ns` and `us` return."""
        return self._built().time_in_picoseconds()

    def peek32(self, address: int, via: Port | None = None) -> int:
        """Read a 32-bit little-endian value, as a bus master sees memory.

        `via` is the master's port to look through, such as `cpu.socket`. It
        may be left out when the platform has exactly one bus master.

        A peek takes no simulated time and nothing in the platform notices
        it, the way a debugger reads memory.
        """
        view = self._view(via)
        data = self._built().debug_read(view.path, address, 4)
        if data is None:
            raise self._nothing_at(address, view)
        return int.from_bytes(data, "little")

    def poke32(self, address: int, value: int, via: Port | None = None) -> None:
        """Write a 32-bit little-endian value, as a bus master sees memory.

        Like a peek, a poke takes no simulated time. `via` works as in `peek32`.
        """
        view = self._view(via)
        if not self._built().debug_write(
            view.path, address, value.to_bytes(4, "little")
        ):
            raise self._nothing_at(address, view)

    def devicetree(self, via: Port | None = None) -> str:
        """The devicetree source for what a bus master can reach.

        `via` is the master's port, as in `peek32`. Works on a description;
        nothing needs to be built.
        """
        return devicetree.generate(self._connections, self._view(via))

    def to_json(self) -> str:
        """The description as JSON: every component and every connection.

        A scripted bus master's script is behavior, not structure, and is
        left out.
        """
        return json.dumps(
            {
                "components": {
                    path: {
                        "implementation": placed.component.implementation,
                        "parameters": placed.component.parameters,
                    }
                    for path, placed in self._placed.items()
                },
                "connections": [
                    {"source": source.path, "sink": sink.path, "trace": trace}
                    for source, sink, trace in self._connections
                ],
            },
            indent=2,
        )

    def _nothing_at(self, address: int, view: Port) -> LookupError:
        return LookupError(
            f"Nothing took a 4-byte access at address {address:#x}, as seen "
            f"from {view.path}. Check the address against the memory map."
        )

    def _view(self, via: Port | None) -> Port:
        """The port a peek or poke looks through."""
        if via is not None:
            return via
        masters = [
            placed
            for placed in self._placed.values()
            if placed.component.is_bus_master
        ]
        if len(masters) != 1:
            raise ValueError(
                f"This platform has {len(masters)} bus masters, so say whose "
                "view of memory you want: pass via=<a master's port>, such as "
                "via=cpu.socket."
            )
        return masters[0].socket

    def refuse_if_built(self, change: str) -> None:
        """Raise if the platform is built, since its topology is then fixed."""
        if self._native is not None:
            raise RuntimeError(
                f"Cannot {change}: this platform is already built. SystemC "
                "fixes the topology once the simulation is created, so "
                "describe everything before calling build()."
            )

    def _built(self) -> _core.Platform:
        if self._native is None:
            raise RuntimeError(
                "This platform is only described so far. Call build() first "
                "to create the simulation."
            )
        return self._native
