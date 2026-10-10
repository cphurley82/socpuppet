"""What a bus master can reach, and at which address.

A platform's address map is not written down in one place. It is what
falls out of the connections: a master is connected to a router, the
router's outputs to devices or to a link, the link to another router, and
so on. This walks it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Iterator, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple, overload

from socpuppet.terminal import BOLD, CYAN, DIM, MAGENTA, table

if TYPE_CHECKING:
    from socpuppet.placed import Port
    from socpuppet.platform import Connection


@dataclasses.dataclass(frozen=True)
class Window:
    """A range of a router that leads on to what passes accesses further.

    That is a link, or another bus. A range that leads straight to what
    answers is that device's own place on the bus and not a window, and
    that goes for the two ranges of a PCIe root complex as well, which
    answers for the device behind it.
    """

    #: The path of the router whose range it is.
    bus: str
    #: Where the range starts in the master's map.
    address: int
    #: How many bytes of it the master can reach.
    size: int

    @property
    def translates(self) -> bool:
        """Whether what is behind the window is at other addresses there.

        A router hands on the offset from the start of its range, so the
        bus behind a window counts from zero. Its addresses are the
        master's own only if the window starts at 0 in the master's map.
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

    def as_json(self) -> dict[str, Any]:
        """The entry as JSON takes it, each window saying if it translates."""
        return dataclasses.asdict(self) | {
            "windows": [
                dataclasses.asdict(window) | {"translates": window.translates}
                for window in self.windows
            ]
        }


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
    return MapEntry(
        address=found.address,
        size=_narrowed(found.limit, placed.component.size_at(found.port.name)),
        component=placed.path,
        port=found.port.name,
        implementation=placed.component.implementation,
        group=_group_of(placed.path, groups),
        windows=found.windows,
    )


def _group_of(path: str, groups: Collection[str]) -> str | None:
    """The innermost of `groups` that the component at `path` is inside."""
    return max(
        (each for each in groups if path.startswith(f"{each}.")),
        key=len,
        default=None,
    )


def render(map_entries: Sequence[MapEntry], color: bool | None = None) -> str:
    """An address map as a table for people, one line for each entry.

    The last column has the windows on the way to an entry, in the order
    an access goes through them. `bus +0x1000_0000` is a window of `bus`
    that starts at that address and translates; `bus =` is one that does
    not (see `Window.translates`).

    `color` defaults to whether standard output wants it.
    """
    return table(
        ("Address", "Size", "What answers", "Model", "Through"),
        [
            (
                format_address(entry.address),
                format_size(entry.size),
                f"{entry.component}.{entry.port}",
                entry.implementation,
                " → ".join(
                    f"{window.bus} +{format_address(window.address)}"
                    if window.translates
                    else f"{window.bus} ="
                    for window in entry.windows
                ),
            )
            for entry in map_entries
        ],
        styles=(BOLD, "", CYAN, DIM, MAGENTA),
        color=color,
    )


def format_address(address: int) -> str:
    """An address as the docs write one: `0x0C00_0000`."""
    return f"0x{address:09_X}"


def format_size(size: int | None) -> str:
    """A number of bytes in the biggest unit that divides it: `64 KiB`.

    A size that nothing says (see `MapEntry.size`) is a question mark.
    """
    if size is None:
        return "?"
    units = ["KiB", "MiB", "GiB", "TiB", "PiB", "EiB"]
    unit = "byte" if size == 1 else "bytes"
    while size % 1024 == 0 and units:
        size //= 1024
        unit = units.pop(0)
    return f"{size} {unit}"


class Reached(NamedTuple):
    """A port that answers accesses, as a bus master finds it."""

    #: The address at which the master finds what is behind the port.
    address: int
    port: Port
    #: How many bytes of it the master can reach from there: the smallest
    #: range mapped on the way. None if nothing on the way sets a limit.
    limit: int | None
    #: The windows on the way, the master's own bus first.
    windows: tuple[Window, ...]


def reachable_ports(
    connections: Collection[Connection], view: Port
) -> Iterator[Reached]:
    """Yield each port that answers accesses made from the port `view`."""
    return _walk(connections, view, _Place())


@dataclasses.dataclass(frozen=True)
class _Place:
    """Where a walk of the address map has got to."""

    #: Where the port the walk is at is in the master's address map.
    base: int = 0
    #: How many bytes from there the master can reach, as `Reached.limit`.
    limit: int | None = None
    #: The ports an access has come through on the way.
    been: tuple[str, ...] = ()
    #: The windows among them.
    windows: tuple[Window, ...] = ()
    #: The range of a router the access has just come out of. It is a
    #: window only if what it leads to passes the access on. Where it
    #: leads to what answers, it is that device's own place on the bus.
    entered: Window | None = None


def _walk(
    connections: Collection[Connection], view: Port, place: _Place
) -> Iterator[Reached]:
    """Yield what answers accesses from the port `view`, which is at `place`."""
    sink = next(
        (each.sink for each in connections if each.source.path == view.path),
        None,
    )
    if sink is None:
        return
    been = place.been
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
        yield Reached(place.base, sink, place.limit, place.windows)
        return
    windows = place.windows
    if place.entered is not None:
        windows = (*windows, place.entered)
    for output, offset, size in routes:
        base = place.base + offset
        yield from _walk(
            connections,
            getattr(sink.placed, output),
            _Place(
                base=base,
                limit=_narrowed(place.limit, size),
                been=(*been, sink.path),
                windows=windows,
                # A way on with no size is no range: a link passes on all
                # there is.
                entered=(
                    None
                    if size is None
                    else Window(
                        sink.placed.path, base, _narrowed(place.limit, size)
                    )
                ),
            ),
        )


@overload
def _narrowed(limit: int | None, size: int) -> int: ...
@overload
def _narrowed(limit: int | None, size: int | None) -> int | None: ...
def _narrowed(limit: int | None, size: int | None) -> int | None:
    """What is left of a limit after a range of `size` bytes on the way."""
    if limit is None or size is None:
        return limit if size is None else size
    return min(limit, size)
