"""Generate a devicetree from a platform description.

A devicetree tells firmware (Zephyr, here) what hardware exists and where.
Generating it from the same description that builds the simulation keeps
the two from drifting apart. No simulation is needed to do it.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from typing import TYPE_CHECKING

from socpuppet.components import Memory

if TYPE_CHECKING:
    from socpuppet.platform import Connection, Placed, Port


def generate(connections: Collection[Connection], view: Port) -> str:
    """The devicetree source for the hardware reachable from the port `view`.

    `connections` are the platform's connections.
    Addresses are the ones a bus master at `view` uses.
    """
    lines = [
        "/dts-v1/;",
        "",
        "/ {",
        "\t#address-cells = <2>;",
        "\t#size-cells = <2>;",
    ]
    for base, placed in sorted(
        _endpoints(connections, view), key=lambda found: found[0]
    ):
        if isinstance(placed.component, Memory):
            size = placed.component.parameters["size"]
            lines += [
                "",
                f"\t{_label(placed.path)}: memory@{base:x} {{",
                '\t\tdevice_type = "memory";',
                f"\t\treg = <{_cells(base)} {_cells(size)}>;",
                "\t};",
            ]
    lines += ["};", ""]
    return "\n".join(lines)


def _endpoints(
    connections: Collection[Connection], view: Port, base: int = 0
) -> Iterator[tuple[int, Placed]]:
    """Yield each component that answers accesses made from `view`.

    Each comes as (address, placed component).
    """
    sink = next(
        (each.sink for each in connections if each.source.path == view.path),
        None,
    )
    if sink is None:
        return
    routes = list(sink.placed.component.routes(sink.name))
    if not routes:
        yield base, sink.placed
    for output, offset in routes:
        yield from _endpoints(
            connections, getattr(sink.placed, output), base + offset
        )


def _label(path: str) -> str:
    """A devicetree label for a component path: `io.ram` becomes `io_ram`."""
    return path.replace(".", "_")


def _cells(value: int) -> str:
    """A 64-bit value as two 32-bit devicetree cells, high half first."""
    return f"{value >> 32:#x} {value & 0xFFFF_FFFF:#x}"
