"""The `socpuppet` command line."""

import argparse
import json
import pathlib
import runpy
import sys
import traceback
from collections.abc import Sequence

from socpuppet import address_map, interrupt_map
from socpuppet.address_map import MapEntry
from socpuppet.interrupt_map import InterruptEntry
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
    _add_description(devicetree)
    devicetree.add_argument(
        "--via",
        metavar="PORT",
        help=(
            "the port of the bus master whose view of memory to print, "
            "such as cpu.socket. Needed when the platform has more than one "
            "bus master."
        ),
    )
    maps = commands.add_parser(
        "address-map",
        help="print what answers at which address in a platform description",
        description=(
            "Print the address map of each bus master in a platform "
            "description, which is what answers at which address, and the "
            "interrupt map, which is whose line is which number. Nothing "
            "is simulated."
        ),
    )
    _add_description(maps)
    maps.add_argument(
        "--via",
        metavar="PORT",
        help=(
            "print only the address map of what starts accesses at this "
            "port, such as cpu.socket. It need not be a bus master's: a "
            "device's own port for DMA has a map too."
        ),
    )
    maps.add_argument(
        "--json",
        action="store_true",
        help="print the maps as JSON, for a program to read",
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
    elif options.command == "address-map":
        maps_of = _maps_as_json if options.json else _maps_as_text
        sys.stdout.write(maps_of(*_maps(options.description, options.via)))
    elif options.command == "devicetree":
        sys.stdout.write(_devicetree(options.description, options.via))


def _add_description(command: argparse.ArgumentParser) -> None:
    """Give a command the description file it works on, as an argument."""
    command.add_argument(
        "description",
        help=(
            "a Python file that leaves its Platform in a variable called "
            "`platform`"
        ),
    )


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


def _maps(
    path: str, via: str | None
) -> tuple[dict[str, list[MapEntry]], list[InterruptEntry]]:
    """The maps of the platform a file describes.

    Every bus master's address map by the path of its socket, or only the
    one from the port `via`, and the interrupt map. What is wrong with the
    file or with the description ends the command with one line that says
    so.
    """
    platform = _load(path)
    try:
        if via is None:
            address_maps = platform.address_maps()
        else:
            address_maps = {via: platform.address_map(platform.port(via))}
    except ValueError as refused:
        sys.exit(f"{path}: {refused}")
    return address_maps, platform.interrupt_map()


def _maps_as_json(
    address_maps: dict[str, list[MapEntry]], interrupts: list[InterruptEntry]
) -> str:
    """The maps as the description's own JSON has them (`Platform.to_json`)."""
    return (
        json.dumps(
            {
                "address_maps": {
                    view: [entry.as_json() for entry in entries]
                    for view, entries in address_maps.items()
                },
                "interrupts": [entry.as_json() for entry in interrupts],
            },
            indent=2,
        )
        + "\n"
    )


def _maps_as_text(
    address_maps: dict[str, list[MapEntry]], interrupts: list[InterruptEntry]
) -> str:
    """The maps for people: a heading and a table for each."""
    sections = [
        (
            f"🧦 The address map, as {view} sees it",
            address_map.render(entries)
            if entries
            else f"Nothing answers an access that starts at {view}.",
        )
        for view, entries in address_maps.items()
    ]
    sections.append(
        (
            "🧦 The interrupt map",
            interrupt_map.render(interrupts)
            if interrupts
            else "No line goes to a numbered input of an interrupt "
            "controller or of a CPU.",
        )
    )
    return "\n\n".join(f"{title}\n\n{body}" for title, body in sections) + "\n"


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
