"""What a bus master can reach, and at which address.

A platform's address map is not written down in one place. It is what
falls out of the connections: a master is connected to a router, the
router's outputs to devices or to a link, the link to another router, and
so on. This walks it.
"""

from __future__ import annotations

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


def reachable_ports(
    connections: Collection[Connection],
    view: Port,
    base: int = 0,
    window: int | None = None,
    been: tuple[str, ...] = (),
) -> Iterator[Reached]:
    """Yield each port that answers accesses made from the port `view`.

    `base`, `window` and `been` are how the walk keeps its place: where
    the port `view` is in the master's address map, how much of it the
    master can reach, and the ports an access has come through on the way.
    A caller leaves them out.
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
        yield Reached(base, sink, window)
    for output, offset, size in routes:
        yield from reachable_ports(
            connections,
            getattr(sink.placed, output),
            base + offset,
            _narrowed(window, size),
            (*been, sink.path),
        )


def _narrowed(window: int | None, size: int | None) -> int | None:
    """What is left of a window after a range of `size` bytes on the way."""
    if window is None or size is None:
        return window if size is None else size
    return min(window, size)
