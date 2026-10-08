"""The `socpuppet` command line."""

import argparse
import pathlib
import runpy
import sys
import traceback
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
    devicetree.add_argument(
        "--via",
        metavar="PORT",
        help=(
            "the port of the bus master whose view of memory to print, "
            "such as cpu.socket. Needed when the platform has more than one "
            "bus master."
        ),
    )
    commands.add_parser(
        "zephyr-module",
        help="print where socpuppet's Zephyr boards are",
        description=(
            "Print the directory of the Zephyr module that holds "
            "socpuppet's boards. Hand it to a Zephyr build with "
            "-DZEPHYR_EXTRA_MODULES=$(socpuppet zephyr-module)."
        ),
    )
    options = parser.parse_args(arguments)

    if options.command == "zephyr-module":
        print(pathlib.Path(__file__).parent / "zephyr_module")
    else:
        sys.stdout.write(_devicetree(options.description, options.via))


def _devicetree(path: str, via: str | None) -> str:
    """The devicetree of the platform a file describes.

    What is wrong with the file or with the description ends the command
    with one line that says so.
    """
    platform = _load(path)
    masters = platform.bus_masters
    if via is None and len(masters) > 1:
        sys.exit(
            f"{path} describes a platform with {len(masters)} bus masters "
            f"({', '.join(master.path for master in masters)}), and each "
            "sees memory its own way. Say whose devicetree to print with "
            f"--via, such as --via {masters[0].path}.socket."
        )
    try:
        return platform.devicetree(None if via is None else platform.port(via))
    except (ValueError, LookupError) as refused:
        sys.exit(f"{path}: {refused}")


def _load(path: str) -> Platform:
    """Run a description file and return the Platform it describes."""
    try:
        names = runpy.run_path(path)
    except OSError as unreadable:
        sys.exit(f"Cannot read {path}: {unreadable.strerror}.")
    except Exception as failure:
        # Whatever the file itself raises. The traceback would be mostly
        # this command's own frames, so the one line of the file is given.
        sys.exit(
            f"{_where(failure, path)}: {type(failure).__name__}: {failure}"
        )
    if "platform" not in names:
        sys.exit(
            f"{path} does not define `platform`. A description file must "
            "leave its Platform in a variable with that name."
        )
    platform = names["platform"]
    if not isinstance(platform, Platform):
        sys.exit(
            f"{path} leaves a {type(platform).__name__} in `platform`, and "
            "that variable has to hold the sp.Platform the file describes."
        )
    return platform


def _where(failure: BaseException, path: str) -> str:
    """The file, and the last of its lines the failure passed through."""
    file = pathlib.Path(path).resolve()
    lines = [
        frame.lineno
        for frame in traceback.extract_tb(failure.__traceback__)
        if pathlib.Path(frame.filename).resolve() == file
    ]
    return f"{path}, line {lines[-1]}" if lines else path
