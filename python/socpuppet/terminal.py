"""Text for a terminal: color where it is wanted, and columns that line up."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence

BOLD, DIM, GREEN, RED, CYAN, MAGENTA, RESET = (
    "\x1b[1m",
    "\x1b[2m",
    "\x1b[32m",
    "\x1b[31m",
    "\x1b[36m",
    "\x1b[35m",
    "\x1b[0m",
)


def wants_color(is_terminal: bool, environment: Mapping[str, str]) -> bool:
    """Whether output should be colored.

    Color suits a terminal; a file or a pipe gets plain text. A non-empty
    NO_COLOR (https://no-color.org) turns color off everywhere.
    """
    return is_terminal and not environment.get("NO_COLOR")


def stdout_wants_color() -> bool:
    """Whether what is printed to standard output should be colored."""
    return wants_color(sys.stdout.isatty(), os.environ)


def table(
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    styles: Sequence[str],
    color: bool | None,
) -> str:
    """Rows of text as a table, under a header, with no line after the last.

    Each column is as wide as its widest cell, with two spaces between one
    and the next. With `color`, each cell is painted with its column's
    code in `styles`, and the header is bold. A `color` of None is
    whether standard output wants it.
    """
    if color is None:
        color = stdout_wants_color()
    widths = [
        max(len(cell) for cell in column)
        for column in zip(header, *rows, strict=True)
    ]

    def line(cells: Sequence[str], codes: Sequence[str]) -> str:
        # The padding goes outside the color, so that the columns are
        # where they would be without it.
        return "  ".join(
            (f"{code}{cell}{RESET}" if color and cell and code else cell)
            + " " * (width - len(cell))
            for cell, code, width in zip(cells, codes, widths, strict=True)
        ).rstrip()

    return "\n".join(
        [
            line(header, [BOLD] * len(header)),
            *(line(row, styles) for row in rows),
        ]
    )
