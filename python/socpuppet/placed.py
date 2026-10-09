"""A component at its place in a platform, and its ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from socpuppet.components import Component, PortSpec, Router
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


class PlacedUart(Placed):
    """A UART at its place in a platform."""

    @property
    def output(self) -> str:
        """Everything the firmware has printed through the UART so far.

        A byte that is not text comes out as the replacement character, �.
        """
        native = self._platform.native()
        return native.uart_output(self.path).decode(errors="replace")
