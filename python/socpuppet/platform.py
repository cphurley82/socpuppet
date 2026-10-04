"""Describe a platform in Python, then build and run it."""

import json

from socpuppet.components import ScriptedBusMaster


class Port:
    """One port of a described component, such as `cpu.socket`."""

    def __init__(self, component_path, name):
        self.path = f"{component_path}.{name}"


class Placed:
    """A component at its place in a platform. Its ports are attributes."""

    def __init__(self, path, component):
        self.path = path
        self.component = component
        self._ports = {name: Port(path, name) for name in component.ports}

    def __getattr__(self, name):
        # Reached only for names that are not ordinary attributes: the ports.
        try:
            return self._ports[name]
        except KeyError:
            raise AttributeError(
                f'"{self.path}" has no port called "{name}". '
                f"Its ports are: {', '.join(self._ports)}."
            ) from None


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
        self._refuse_if_built("add a component")
        if path in self._placed:
            raise ValueError(
                f'There is already a component called "{path}". '
                "Each component needs its own name."
            )
        placed = Placed(path, component)
        self._placed[path] = placed
        return placed

    def group(self, name):
        """A named group of components, such as a die."""
        return Group(self, name)

    def connect(self, source, sink):
        """Connect a source port (an initiator) to a sink port (a target)."""
        self._refuse_if_built("connect ports")
        self._connections.append((source, sink))

    def build(self):
        """Create the simulation from the description."""
        self._refuse_if_built("build it again")
        from socpuppet import _core  # the simulator loads here, not on import

        native = _core.Platform()
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

    def _refuse_if_built(self, change):
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
