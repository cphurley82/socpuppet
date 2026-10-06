"""What a bus master can reach, and at which address.

A platform's address map is not written down in one place. It is what
falls out of the connections: a master is connected to a router, the
router's outputs to devices or to a link, the link to another router, and
so on. This walks it.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from socpuppet.platform import Connection, Port


def reachable_ports(
    connections: Collection[Connection], view: Port, base: int = 0
) -> Iterator[tuple[int, Port]]:
    """Yield each port that answers accesses made from the port `view`.

    Each comes as (address, port): the address at which a bus master at
    `view` finds what is behind the port.
    """
    sink = next(
        (each.sink for each in connections if each.source.path == view.path),
        None,
    )
    if sink is None:
        return
    routes = list(sink.placed.component.routes(sink.name))
    if not routes:
        yield base, sink
    for output, offset in routes:
        yield from reachable_ports(
            connections, getattr(sink.placed, output), base + offset
        )
