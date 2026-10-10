"""Whose interrupt line is which number, to the firmware that takes it.

🎓 A device asks for its CPU's attention by raising a line. The line goes
to an input of an interrupt controller, or of the CPU itself, and the
input's number is all the firmware knows the device by. Like the address
map, this is nowhere written down: it falls out of which wire was
connected to which port.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Iterator, Sequence
from typing import TYPE_CHECKING

from socpuppet._terminal import BOLD, CYAN, stdout_wants_color, table

if TYPE_CHECKING:
    from socpuppet.platform import Connection


@dataclasses.dataclass(frozen=True)
class InterruptEntry:
    """One line of a platform's interrupt map: a line, and its number."""

    #: The path of the component that takes the line, such as `ssd.plic`.
    controller: str
    #: Which of the controller's interrupts the line is.
    number: int
    #: The port that drives the line, such as `ssd.dma.irq`.
    line: str


def entries(connections: Collection[Connection]) -> list[InterruptEntry]:
    """The interrupt map, in order of controller and then of number.

    `connections` are the platform's connections. A line to an input that
    has no number, such as an input of a CPU's stand-in, is left out.
    """
    return sorted(
        _lines(connections),
        key=lambda entry: (entry.controller, entry.number),
    )


def render(entries: Sequence[InterruptEntry], color: bool | None = None) -> str:
    """An interrupt map as a table for people, one line for each interrupt.

    `color` defaults to whether standard output wants it.
    """
    if color is None:
        color = stdout_wants_color()
    return table(
        ("Controller", "Number", "Line"),
        [
            (entry.controller, str(entry.number), entry.line)
            for entry in entries
        ],
        styles=(CYAN, BOLD, ""),
        color=color,
    )


def _lines(connections: Collection[Connection]) -> Iterator[InterruptEntry]:
    """Yield an entry for each connection that ends at a numbered input."""
    for source, sink, _ in connections:
        number = sink.placed.component.interrupt_number(sink.name)
        if number is not None:
            yield InterruptEntry(sink.placed.path, number, source.path)
