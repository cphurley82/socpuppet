"""Transaction traces: what crossed the connections you asked to watch."""

import json
import os
import sys
from dataclasses import dataclass

_BOLD, _DIM, _GREEN, _RED, _CYAN, _RESET = (
    "\x1b[1m",
    "\x1b[2m",
    "\x1b[32m",
    "\x1b[31m",
    "\x1b[36m",
    "\x1b[0m",
)


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
    def from_native(cls, native):
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


def wants_color(is_terminal, environment):
    """Whether output should be colored.

    Color suits a terminal; a file or a pipe gets plain text. A non-empty
    NO_COLOR (https://no-color.org) turns color off everywhere.
    """
    return is_terminal and not environment.get("NO_COLOR")


def render(records, color=None):
    """The trace as text for people, one line per transaction.

    `color` defaults to whether standard output wants it (see `wants_color`).
    """
    if color is None:
        color = wants_color(sys.stdout.isatty(), os.environ)

    def paint(code, text):
        return f"{code}{text}{_RESET}" if color else text

    lines = []
    for record in records:
        command = paint(
            _GREEN if record.command == "read" else _CYAN,
            f"{record.command:<5}",
        )
        time = paint(_DIM, f"{record.time / 1000:g} ns".rjust(12))
        address = paint(_BOLD, f"{record.address:#010x}")
        route = paint(_DIM, f"{record.source} → {record.sink}")
        lines.append(
            f"{time}  {command} {address}  {record.data.hex(' ')}  "
            f"{'✅' if record.ok else paint(_RED, '❌')}  {route}"
        )
    return "\n".join(lines)


def to_json_lines(records):
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
