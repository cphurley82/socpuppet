"""Transaction traces: what crossed the connections you asked to watch."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

from socpuppet._terminal import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    RESET,
    stdout_wants_color,
    wants_color,
)

__all__ = ["TraceRecord", "render", "to_json_lines", "wants_color"]


@dataclass(frozen=True)
class TraceRecord:
    """One transaction seen crossing a traced connection."""

    time: int  #: when it completed, in picoseconds (compare with `ns`, `us`)
    source: str  #: the port it came from, such as "compute.cpu.socket"
    sink: str  #: the port it went to
    command: str  #: "read" or "write"
    address: int
    data: bytes  #: what was written, or what the read returned
    ok: bool  #: False if the target answered with an error

    @classmethod
    def from_native(
        cls, native: tuple[int, str, str, bool, int, bytes, bool]
    ) -> Self:
        """A record from the simulator's tuple.

        The tuple is (time, source, sink, is_write, address, data, ok).
        """
        time, source, sink, is_write, address, data, ok = native
        return cls(
            time,
            source,
            sink,
            "write" if is_write else "read",
            address,
            data,
            ok,
        )


def render(records: Iterable[TraceRecord], color: bool | None = None) -> str:
    """The trace as text for people, one line per transaction.

    `color` defaults to whether standard output wants it (see `wants_color`).
    """
    if color is None:
        color = stdout_wants_color()

    def paint(code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if color else text

    lines = []
    for record in records:
        command = paint(
            GREEN if record.command == "read" else CYAN,
            f"{record.command:<5}",
        )
        time = paint(DIM, f"{record.time / 1000:g} ns".rjust(12))
        address = paint(BOLD, f"{record.address:#010x}")
        route = paint(DIM, f"{record.source} → {record.sink}")
        lines.append(
            f"{time}  {command} {address}  {record.data.hex(' ')}  "
            f"{'✅' if record.ok else paint(RED, '❌')}  {route}"
        )
    return "\n".join(lines)


def to_json_lines(records: Iterable[TraceRecord]) -> str:
    """The trace for machines: one JSON object per line.

    No color, and the field names are stable.
    """
    return "".join(
        json.dumps(
            {
                "time_ps": record.time,
                "source": record.source,
                "sink": record.sink,
                "command": record.command,
                "address": record.address,
                "data": record.data.hex(),
                "ok": record.ok,
            }
        )
        + "\n"
        for record in records
    )
