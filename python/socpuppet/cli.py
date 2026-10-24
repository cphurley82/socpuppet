"""The `socpuppet` command line."""

import argparse
import json
import os
import pathlib
import runpy
import signal
import sys
import threading
import traceback
import typing
from collections.abc import Sequence

from socpuppet import address_map, boot_image, drive, interrupt_map, linux, run
from socpuppet.address_map import MapEntry
from socpuppet.boards import real_host
from socpuppet.boards.host import HOST_CPUS, HostCpu, switched_off
from socpuppet.components import Dialect, QboxCpu
from socpuppet.errors import SlirpUnavailable
from socpuppet.ethernet_cable import EthernetCable
from socpuppet.interactive import interact
from socpuppet.interrupt_map import InterruptEntry
from socpuppet.placed import PlacedNet
from socpuppet.platform import Platform
from socpuppet.pump import pump
from socpuppet.time import ms

#: The port of this machine's that `socpuppet linux` forwards to Linux's
#: ssh, by default: 22 is this machine's own, and 2222 is the usual next.
SSH_PORT = 2222


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
            "firmware/build.py builds, looked for in SOCPUPPET_FIRMWARE_DIR "
            "or else in build/firmware"
        ),
    )
    _add_cpu(runner)
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
    linux_command = commands.add_parser(
        "linux",
        help="boot Linux on the host, with this terminal at its console",
        description=(
            "Boot Linux on the host, the quick way, and put this terminal "
            "at its console: the boot scrolls by, and then its shell is "
            "yours. OpenSBI, the kernel and its root filesystem are the "
            "ones firmware/build.py builds, looked for in "
            "SOCPUPPET_FIRMWARE_DIR or else in build/firmware. Ctrl-] "
            "leaves."
        ),
    )
    _add_cpu(linux_command, speed=", and which boots Linux ten times as fast")
    linux_command.add_argument(
        "--root",
        choices=typing.get_args(linux.Root.__value__),
        default="virtio",
        help=(
            "where Linux's root filesystem is: virtio, the virtio disk, "
            "or drive, the SSD across the die-to-die link, whose firmware "
            "and the IO manager's are the ones firmware/build.py zephyr "
            "builds (the default is %(default)s)"
        ),
    )
    linux_command.add_argument(
        "--ssh-port",
        type=int,
        default=SSH_PORT,
        metavar="PORT",
        help=(
            "the port of this machine's that reaches Linux's ssh, through "
            "a cable to this machine's network (libslirp), or 0 to leave "
            "the cable out (the default is %(default)s)"
        ),
    )
    drive_command = commands.add_parser(
        "drive",
        help="put the puppet's drive on this machine's own PCIe bus",
        description=(
            "Put the puppet's drive on this machine's own PCIe bus, "
            "through pciem, where this machine's Linux finds it as it "
            "would a card in a slot: its nvme driver binds it, and lsblk "
            "lists it. It takes a build of socpuppet with pciem, on a "
            "machine whose Linux has pciem loaded (docs/setup.md, and "
            "`tools/doctor.py pciem`). The SSD's firmware is the one "
            "firmware/build.py zephyr builds, looked for in "
            "SOCPUPPET_FIRMWARE_DIR or else in build/firmware. Ctrl-C ends "
            "it, once Linux has let go of the drive."
        ),
    )
    drive_command.add_argument(
        "--firmware",
        choices=typing.get_args(drive.Firmware.__value__),
        default="zephyr",
        help=(
            "which drive it is: zephyr, the SSD with its own firmware, or "
            "behavioral, the stand-in, which has no CPU or firmware (the "
            "default is %(default)s)"
        ),
    )
    drive_command.add_argument(
        "--blocks",
        type=int,
        default=drive.BLOCKS,
        help=(
            "how many 512-byte blocks the drive holds (the default is "
            "%(default)s, 64 MiB)"
        ),
    )
    options = parser.parse_args(arguments)

    if options.command == "linux":
        _linux(options.cpu, options.root, options.ssh_port)
    elif options.command == "drive":
        _drive(options.firmware, options.blocks)
    elif options.command == "run":
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


def _linux(cpu: HostCpu | None, root: linux.Root, ssh_port: int) -> None:
    """Boot Linux on the host, with this terminal at its console.

    It says first, on standard error, which CPU it boots on and that
    Ctrl-] leaves. Then, in one line, how to reach Linux by ssh, through
    a cable that forwards `ssh_port` of this machine's to Linux's 22, or
    why ssh is off. With an `ssh_port` of 0 there is no cable, and
    nothing is said of ssh. What is typed waits for the shell's first
    prompt. It ends when Linux switches the host off (`poweroff`), at
    Ctrl-], or when the reader of its output has gone (`socpuppet linux
    | head -1`), and says which.

    `cpu` is the host's CPU, or None for the one SOCPUPPET_CPU names, and
    `root` where the root filesystem is (`linux.host_with_linux`). An
    image, a tool such as dtc, or a CPU that this build has not ends the
    command with one line that says how to get it.
    """
    try:
        board = linux.host_with_linux(
            run.firmware_directory(), cpu=cpu, root=root
        )
    except (FileNotFoundError, ValueError) as refused:
        sys.exit(str(refused))
    # Said on standard error: standard output is the machine's console.
    on_qbox = board.cpu.component.implementation == QboxCpu.implementation
    print(
        "🧦 Booting 🐧 Linux on the host's "
        f"{board.cpu.component.implementation}. Its shell prompts "
        + (
            "in seconds."
            if on_qbox
            else "in a minute or two, after a quiet spell in the middle "
            f"(in seconds on {QboxCpu.implementation})."
        )
        + " Ctrl-] leaves.",
        file=sys.stderr,
        flush=True,
    )
    assert board.virtio is not None  # the host was described with them
    cables = _cables(board.virtio.net, ssh_port)
    console = board.virtio.console
    try:
        interact(
            board.platform,
            screen=[board.uart, console],
            keyboard=console,
            until=lambda: switched_off(board),
            ready=lambda: linux.PROMPT.search(console.output) is not None,
            far_ends=cables,
        )
    except BrokenPipeError:
        # `socpuppet linux | head -1`: the reader has its line and has
        # gone, which is its choice, not a failure. ⚠️ The interpreter
        # flushes standard output once more as it ends, and would fail
        # the same way: so from here it goes nowhere. 💡 Python's own
        # recipe for this (`signal`, "Note on SIGPIPE").
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        ended = (
            "🧦 The console's reader has gone. The simulation ends with "
            "the command."
        )
    else:
        ended = (
            "🐧 Linux switched the host off."
            if switched_off(board)
            else "🧦 Left. The simulation ends with the command."
        )
    finally:
        for cable in cables:
            cable.close()
    # On a line of its own: the cursor may be at the end of Linux's prompt.
    print(f"\n{ended}", file=sys.stderr)


def _cables(card: PlacedNet, port: int) -> list[EthernetCable]:
    """🔌 A cable from `card` to this machine's network, if any.

    The cable forwards `port` of this machine's to Linux's ssh, and there
    is none for a `port` of 0. It says on standard error how to reach
    Linux by ssh, or why ssh is off, such as libslirp missing or `port`
    taken, and then there is no cable. Linux boots either way.
    """
    if port == 0:
        return []
    try:
        cable = EthernetCable(card, forward={port: 22})
    except (SlirpUnavailable, OSError) as refused:
        print(
            f"🔌 ssh is off: {refused}"
            + (
                " --ssh-port picks another, and 0 leaves the cable out."
                if isinstance(refused, OSError)
                else ""
            ),
            file=sys.stderr,
        )
        return []
    print(
        f"🔌 ssh -p {port} root@localhost reaches Linux's shell once it "
        "prompts, with no password. Its host key is new at each boot.",
        file=sys.stderr,
        flush=True,
    )
    return [cable]


def _drive(firmware: drive.Firmware, blocks: int) -> None:
    """Put the puppet's drive on this machine's bus, until Ctrl-C.

    It says on standard error where on the bus the drive is, and that
    Ctrl-C ends it. A Ctrl-C while a driver of Linux's still holds the
    drive says how to let it go, and the command ends once Linux has; a
    second pulls the drive out anyway. A firmware image or a pciem that
    this build has not, a /dev/pciem that refuses, or a drive from before
    still on the bus ends the command with one line that says what to do.
    """
    try:
        board = drive.on_this_machine(
            run.firmware_directory(), firmware=firmware, blocks=blocks
        )
    except (OSError, ValueError) as refused:
        sys.exit(str(refused))
    try:
        function = real_host.puppet_function()
    except RuntimeError as two_drives:
        sys.exit(str(two_drives))
    assert function is not None  # it was put on the bus as it started
    interrupted = threading.Event()

    def interrupt(*_: object) -> None:
        interrupted.set()

    signal.signal(signal.SIGINT, interrupt)
    which = (
        "SSD, with its Zephyr firmware,"
        if firmware == "zephyr"
        else "🎭 behavioral drive"
    )
    print(
        f"🧦 The puppet's {which} is on this machine's PCIe bus, at "
        f"{real_host.PCI_DEVICES / function}. 🐧 lsblk lists it once "
        "Linux's nvme driver has bound it. Ctrl-C ends it.",
        file=sys.stderr,
        flush=True,
    )
    pump(board.platform, far_ends=[board.host], until=interrupted.is_set)
    if real_host.held(function):
        print(
            "\n🐧 Linux still holds the drive. Unmount what is mounted from "
            f"it, then let it go with `echo {function} | sudo tee "
            f"{real_host.unbind(function)}`, and the command ends. Ctrl-C "
            "again pulls the drive out anyway, as a card is pulled from its "
            "slot.",
            file=sys.stderr,
            flush=True,
        )
        interrupted.clear()
        pump(
            board.platform,
            far_ends=[board.host],
            until=lambda: interrupted.is_set() or not real_host.held(function),
        )
    let_go = not real_host.held(function)
    print(
        "🐧 Linux has let go of the drive. The simulation ends with the "
        "command."
        if let_go
        else "🧦 Pulled out. Linux gives up on the drive in its own time, "
        "seconds for each command it was owed.",
        file=sys.stderr,
    )


def _add_cpu(command: argparse.ArgumentParser, *, speed: str = "") -> None:
    """Give a command the host's choice of CPU, as an option.

    `speed` is what its help says of QBox's CPU's speed, if anything.
    """
    command.add_argument(
        "--cpu",
        choices=HOST_CPUS,
        metavar="CPU",
        help=(
            "the host's CPU: dbt_rise_cpu, socpuppet's own, or qbox_cpu, "
            f"QEMU's, which only a build with QBox has{speed}. The default "
            "is the one SOCPUPPET_CPU names, or else dbt_rise_cpu"
        ),
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
