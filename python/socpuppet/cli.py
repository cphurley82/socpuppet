"""The `socpuppet` command line."""

import argparse
import runpy
import sys
from collections.abc import Sequence

from socpuppet.platform import Platform


def main(arguments: Sequence[str] | None = None) -> None:
    """Run the `socpuppet` command with `arguments`, or the process's own."""
    parser = argparse.ArgumentParser(
        prog="socpuppet",
        description="🧦 A whole SoC, with Python pulling the strings.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    devicetree = commands.add_parser(
        "devicetree",
        help="print the devicetree for a platform description",
        description=(
            "Print the devicetree for a platform description. "
            "Nothing is simulated."
        ),
    )
    devicetree.add_argument(
        "description",
        help=(
            "a Python file that leaves its Platform in a variable called "
            "`platform`"
        ),
    )
    options = parser.parse_args(arguments)

    sys.stdout.write(_load(options.description).devicetree())


def _load(path: str) -> Platform:
    """Run a description file and return the Platform it describes."""
    names = runpy.run_path(path)
    if "platform" not in names:
        sys.exit(
            f"{path} does not define `platform`. A description file must "
            "leave its Platform in a variable with that name."
        )
    platform: Platform = names["platform"]
    return platform
