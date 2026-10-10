"""What a bus master can reach, and at which address.

A platform's address map is not written down in one place. It is what
falls out of the connections: a master is connected to a router, the
router's outputs to devices or to a link, the link to another router, and
so on. This walks it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Iterator
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from socpuppet.placed import Port
    from socpuppet.platform import Connection


class Reached(NamedTuple):
    """A port that answers accesses, as a bus master finds it."""

    #: The address at which the master finds what is behind the port.
    address: int
    port: Port
    #: How many bytes of it the master can reach from there: the smallest
    #: range mapped on the way. None if nothing on the way sets a limit.
    window: int | None
    #: The windows on the way, the master's own bus first.
    windows: tuple[Window, ...]


@dataclasses.dataclass(frozen=True)
class Window:
    """A range of one bus that leads onto another, as a master finds it."""

    #: The router whose range it is.
    bus: str
    #: Where the range starts in the master's map. What is behind the
    #: window counts its addresses from here.
    address: int
    size: int

    @property
    def translates(self) -> bool:
        """Whether an address changes on its way through the window.

        A router hands its target the offset from the start of the range.
        So only a window that starts at address 0 leaves addresses as
        they are, and what is behind any other counts from zero.
        """
        return self.address != 0


@dataclasses.dataclass(frozen=True)
class MapEntry:
    """One line of a bus master's address map: what answers at an address."""

    address: int
    #: How many bytes answer from there on. None if nothing says: the
    #: component has no size of its own, and no router's range is on the
    #: way to it.
    size: int | None
    #: The path of the component that answers there, such as `io.uart`.
    component: str
    #: Which of the component's ports the accesses arrive at.
    port: str
    #: The component's model, by its name in the C++ registry.
    implementation: str
    #: The group the component is in, such as a die. None if it is in none.
    group: str | None
    #: The windows an access goes through to get there, the master's own
    #: bus first. Empty for what is on the master's own bus.
    windows: tuple[Window, ...]


def entries(
    connections: Collection[Connection],
    view: Port,
    groups: Collection[str],
) -> list[MapEntry]:
    """The address map as the port `view` sees it, lowest address first.

    `connections` are the platform's connections, and `groups` the paths
    of its groups.
    """
    return sorted(
        (_entry(found, groups) for found in reachable_ports(connections, view)),
        key=lambda entry: entry.address,
    )


def _entry(found: Reached, groups: Collection[str]) -> MapEntry:
    placed = found.port.placed
    component = placed.component
    return MapEntry(
        address=found.address,
        size=_narrowed(found.window, component.size_at(found.port.name)),
        component=placed.path,
        port=found.port.name,
        implementation=component.implementation,
        # The innermost of the groups the component is inside.
        group=max(
            (each for each in groups if placed.path.startswith(f"{each}.")),
            key=len,
            default=None,
        ),
        windows=found.windows,
    )


def reachable_ports(
    connections: Collection[Connection],
    view: Port,
    base: int = 0,
    window: int | None = None,
    been: tuple[str, ...] = (),
    windows: tuple[Window, ...] = (),
    crossed: Window | None = None,
) -> Iterator[Reached]:
    """Yield each port that answers accesses made from the port `view`.

    The rest is how the walk keeps its place, and a caller leaves it out:
    where the port `view` is in the master's address map, how much of it
    the master can reach, the ports an access has come through on the
    way, the windows among them, and the range of a router it has just
    come out of. That last one is a window only if what it leads to
    passes the access on. Where it leads to what answers, it is that
    device's own place on the bus.
    """
    sink = next(
        (each.sink for each in connections if each.source.path == view.path),
        None,
    )
    if sink is None:
        return
    if sink.path in been:
        raise ValueError(
            "The address map loops: an access comes back to "
            f"{sink.path}, where it has been, by way of "
            f"{' -> '.join((*been[been.index(sink.path) :], sink.path))}. "
            "Somewhere on that way a router's output leads back to one of "
            "its own inputs."
        )
    routes = list(sink.placed.component.routes(sink.name))
    if not routes:
        yield Reached(base, sink, window, windows)
        return
    if crossed is not None:
        windows = (*windows, crossed)
    for output, offset, size in routes:
        yield from reachable_ports(
            connections,
            getattr(sink.placed, output),
            base + offset,
            _narrowed(window, size),
            (*been, sink.path),
            windows,
            None
            if size is None
            else Window(
                sink.placed.path, base + offset, min(size, window or size)
            ),
        )


def _narrowed(window: int | None, size: int | None) -> int | None:
    """What is left of a window after a range of `size` bytes on the way."""
    if window is None or size is None:
        return window if size is None else size
    return min(window, size)
