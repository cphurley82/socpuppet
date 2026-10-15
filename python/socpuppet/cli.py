"""The `socpuppet` command line."""

import argparse
import json
import pathlib
import runpy
import sys
import traceback
import typing
from collections.abc import Sequence

from socpuppet import address_map, boot_image, interrupt_map, run
from socpuppet.address_map import MapEntry
from socpuppet.boards.host import HOST_CPUS
from socpuppet.components import Dialect
from socpuppet.interrupt_map import InterruptEntry
from socpuppet.platform import Platform
from socpuppet.time import ms


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
    devicetree.add_argument(
        "--dialect",
        choices=typing.get_args(Dialect.__value__),
        default="zephyr",
        help=(
            "whose bindings to write it in: Zephyr's (the default), or "
            "Linux's, which OpenSBI and Linux read"
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
    image = commands.add_parser(
        "boot-image",
        help="wrap a firmware ELF file as an image a boot ROM can start",
        description=(
            "Wrap the program in an ELF file as a boot image: its bytes as "
            "they will be in memory, behind a header that says where they "
            "go, where the CPU starts, and a CRC to check them by. The "
            "image is what a platform's flash is filled with: "
            "platform.load_binary(image, at=<where the flash is>)."
        ),
    )
    image.add_argument("elf", help="the firmware, as a linker wrote it")
    image.add_argument(
        "-o",
        "--output",
        required=True,
        metavar="FILE",
        help="where to write the image",
    )
    image.add_argument(
        "--argument",
        type=lambda number: int(number, 0),
        default=0,
        metavar="NUMBER",
        help=(
            "what the boot ROM hands the program in a1, such as the "
            "address of a devicetree (default: 0)"
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
    runner = commands.add_parser(
        "run",
        help="run a firmware image on a board and print its console",
        description=(
            "Run a firmware image on one of socpuppet's boards and print "
            "what it says on its console."
        ),
    )
    runner.add_argument("image", help="the firmware, as a linker wrote it")
    runner.add_argument(
        "--board",
        required=True,
        metavar="BOARD",
        help=f"the board to run it on: {', '.join(run.BOARDS)}",
    )
    runner.add_argument(
        "--shield",
        action="append",
        default=[],
        metavar="SHIELD",
        help="a shield the board has on, as the image was built with it",
    )
    runner.add_argument(
        "--boot",
        choices=("rom", "ram"),
        default="rom",
        help=(
            "how the CPU gets the image: from its boot ROM, which finds it "
            "in the flash as silicon does (the default), or loaded straight "
            "into RAM, which is quicker. The ROM's own program is one that "
            "firmware/build.sh builds, looked for in SOCPUPPET_FIRMWARE_DIR "
            "or else in build/firmware"
        ),
    )
    runner.add_argument(
        "--cpu",
        choices=HOST_CPUS,
        metavar="CPU",
        help=(
            "the host's CPU: dbt_rise_cpu, socpuppet's own, or qbox_cpu, "
            "QEMU's, which only a build with QBox has. The default is the "
            "one SOCPUPPET_CPU names, or else dbt_rise_cpu"
        ),
    )
    runner.add_argument(
        "--until",
        type=int,
        default=30_000,
        metavar="MS",
        help=(
            "stop after this many milliseconds of simulated time (the "
            "default is %(default)s)"
        ),
    )
    options = parser.parse_args(arguments)

    if options.command == "run":
        run.run(
            options.image,
            options.board,
            options.shield,
            from_rom=options.boot == "rom",
            until=ms(options.until),
            host_cpu=options.cpu,
        )
    elif options.command == "zephyr-module":
        print(pathlib.Path(__file__).parent / "zephyr_module")
    elif options.command == "boot-image":
        print(_boot_image(options.elf, options.output, options.argument))
    elif options.command == "address-map":
        maps_of = _maps_as_json if options.json else _maps_as_text
        sys.stdout.write(maps_of(*_maps(options.description, options.via)))
    elif options.command == "devicetree":
        sys.stdout.write(
            _devicetree(options.description, options.via, options.dialect)
        )


def _add_description(command: argparse.ArgumentParser) -> None:
    """Give a command the description file it works on, as an argument."""
    command.add_argument(
        "description",
        help=(
            "a Python file that leaves its Platform in a variable called "
            "`platform`"
        ),
    )


def _boot_image(elf: str, output: str, argument: int) -> str:
    """Write the boot image of an ELF file, and say what was written.

    A file that is not there or is no program, or an image that cannot be
    written where it was asked for, ends the command with one line that
    says so.
    """
    try:
        image = boot_image.from_elf(elf, argument=argument)
    except (FileNotFoundError, ValueError) as refused:
        sys.exit(str(refused))
    try:
        pathlib.Path(output).write_bytes(image.to_bytes())
    except OSError as unwritable:
        sys.exit(f"Cannot write {output}: {unwritable.strerror}.")
    return (
        f"{output}: the boot image `{image.name}`, {len(image.payload)} "
        f"bytes for a {image.xlen}-bit CPU, to load at "
        f"{image.load_address:#x} and start at {image.entry:#x}."
    )


def _devicetree(path: str, via: str | None, dialect: Dialect) -> str:
    """The devicetree of the platform a file describes, in a dialect.

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
        return platform.devicetree(
            None if via is None else platform.port(via), dialect=dialect
        )
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
