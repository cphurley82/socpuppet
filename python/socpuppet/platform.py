"""Describe a platform in Python, then build and run it."""

import json
import os
import sys

from socpuppet import devicetree
from socpuppet.components import Router, ScriptedBusMaster


class Port:
    """One port of a described component, such as `cpu.socket`."""

    def __init__(self, placed, name):
        self.placed = placed
        self.name = name
        self.path = f"{placed.path}.{name}"


class Placed:
    """A component at its place in a platform. Its ports are attributes."""

    def __init__(self, platform, path, component):
        self._platform = platform
        self.path = path
        self.component = component

    def __getattr__(self, name):
        # Reached only for names that are not ordinary attributes: the ports.
        if name in self.component.ports:
            return Port(self, name)
        raise AttributeError(
            f'"{self.path}" has no port called "{name}". '
            f"Its ports are: {', '.join(self.component.ports)}."
        )


class PlacedRouter(Placed):
    """A router at its place in a platform."""

    def map(self, target, base):
        """Route accesses starting at `base` to the port `target`.

        The range is as long as the target component's own size, and the
        target sees addresses as offsets from `base`.
        """
        self._platform.refuse_if_built("map a range")
        size = target.placed.component.parameters.get("size")
        if size is None:
            raise ValueError(
                f"Cannot map {target.path}: only a component with a size of its own, "
                "such as a Memory, can be mapped onto a router."
            )
        output = self.component.add_output(base, size, label=target.path)
        self._platform.connect(Port(self, output), target)


def wants_color(is_terminal, environment):
    """Whether output should be colored.

    Color suits a terminal; a file or a pipe gets plain text. A non-empty
    NO_COLOR (https://no-color.org) turns color off everywhere.
    """
    return is_terminal and not environment.get("NO_COLOR")


class Group:
    """A level of naming, such as a die. Components added here get its path as a prefix."""

    def __init__(self, platform, path):
        self._platform = platform
        self._path = path

    def add(self, name, component):
        """Place `component` inside this group and return it with its ports."""
        return self._platform.add(f"{self._path}.{name}", component)

    def group(self, name):
        """A group nested inside this one."""
        return Group(self._platform, f"{self._path}.{name}")


class Platform:
    """A platform description, and once built, the running simulation.

    Describe first (`add`, `connect`), then `build()`, then `run()`.
    Describing needs only Python; the simulator is loaded by `build()`.
    """

    def __init__(self):
        self._placed = {}
        self._connections = []
        self._native = None

    def add(self, path, component):
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

    def group(self, name):
        """A named group of components, such as a die."""
        return Group(self, name)

    def connect(self, source, sink):
        """Connect a source port (an initiator) to a sink port (a target)."""
        self.refuse_if_built("connect ports")
        self._connections.append((source, sink))

    def build(self):
        """Create the simulation from the description."""
        self.refuse_if_built("build it again")
        from socpuppet import _core  # the simulator loads here, not on import

        native = _core.Platform(color_log=wants_color(sys.stdout.isatty(), os.environ))
        for path, placed in self._placed.items():
            native.add(path, placed.component.implementation, placed.component.parameters)
            placed.component.configure(native, path)
        for source, sink in self._connections:
            native.bind(source.path, sink.path)
        native.elaborate()
        self._native = native

    def run(self, duration=None):
        """Run for `duration` (see `ns`, `us`, `ms`), or until nothing is left to do."""
        if duration is None:
            self._built().run()
        else:
            self._built().run_for(duration)

    def step(self):
        """Move to the next moment anything is scheduled for, and let it happen.

        Returns False if nothing was left to do.
        """
        return self._built().step()

    def run_until(self, condition, timeout=None):
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
    def time(self):
        """The current simulated time, in the same unit `ns`, `us` and `ms` return."""
        return self._built().time_in_picoseconds()

    def peek32(self, address, via=None):
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

    def poke32(self, address, value, via=None):
        """Write a 32-bit little-endian value, as a bus master sees memory.

        Like a peek, a poke takes no simulated time. `via` works as in `peek32`.
        """
        view = self._view(via)
        if not self._built().debug_write(view.path, address, value.to_bytes(4, "little")):
            raise self._nothing_at(address, view)

    def devicetree(self, via=None):
        """The devicetree source for what a bus master can reach.

        `via` is the master's port, as in `peek32`. Works on a description;
        nothing needs to be built.
        """
        return devicetree.generate(self._connections, self._view(via))

    def to_json(self):
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
                    {"source": source.path, "sink": sink.path}
                    for source, sink in self._connections
                ],
            },
            indent=2,
        )

    def _nothing_at(self, address, view):
        return LookupError(
            f"Nothing took a 4-byte access at address {address:#x}, as seen from "
            f"{view.path}. Check the address against the memory map."
        )

    def _view(self, via):
        """The port a peek or poke looks through."""
        if via is not None:
            return via
        masters = [
            placed
            for placed in self._placed.values()
            if isinstance(placed.component, ScriptedBusMaster)
        ]
        if len(masters) != 1:
            raise ValueError(
                f"This platform has {len(masters)} bus masters, so say whose view of "
                "memory you want: pass via=<a master's port>, such as via=cpu.socket."
            )
        return masters[0].socket

    def refuse_if_built(self, change):
        """Raise if the platform is built, since its topology is then fixed."""
        if self._native is not None:
            raise RuntimeError(
                f"Cannot {change}: this platform is already built. SystemC fixes the "
                "topology once the simulation is created, so describe everything "
                "before calling build()."
            )

    def _built(self):
        if self._native is None:
            raise RuntimeError(
                "This platform is only described so far. Call build() first to create "
                "the simulation."
            )
        return self._native
