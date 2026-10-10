"""Text for a terminal: color where it is wanted."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

BOLD, DIM, GREEN, RED, CYAN, RESET = (
    "\x1b[1m",
    "\x1b[2m",
    "\x1b[32m",
    "\x1b[31m",
    "\x1b[36m",
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
