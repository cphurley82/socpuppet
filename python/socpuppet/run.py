"""`socpuppet run`: one firmware image run on one of socpuppet's boards."""

import os
import pathlib
import sys
from collections.abc import Callable, Sequence
from typing import NamedTuple

from socpuppet import boot_image, ztest
from socpuppet.boards import boot
from socpuppet.boards.cpu_kit import CpuKit
from socpuppet.boards.host import host
from socpuppet.boards.io_manager import io_manager, one_round_trip
from socpuppet.boards.scripted_host import bring_up_the_drive, idle_host
from socpuppet.boards.ssd import ssd
from socpuppet.components import DbtRiseCpu, SystemController
from socpuppet.errors import NvmeError
from socpuppet.ops import Steps
from socpuppet.placed import Placed, PlacedUart
from socpuppet.platform import Platform
from socpuppet.time import ms
from socpuppet.transcript import Transcript


class _Stage(NamedTuple):
    """A board that has been described, and what of it an image is run with."""

    platform: Platform
    cpu: Placed
    #: The CPU's console.
    uart: PlacedUart
    #: The CPU's system controller, which tells a boot ROM where the image is.
    syscon: Placed


class _Board(NamedTuple):
    """One of the boards an image can be run on."""

    #: The shields it takes. 🎓 A shield is Zephyr's word for something
    #: plugged into a board, which an image is built with or without.
    shields: tuple[str, ...]
    #: Describes it, with the shields that are on it and what its CPU
    #: starts in.
    describe: Callable[[Sequence[str], boot.Boot | None], _Stage]


def _host(shields: Sequence[str], how: boot.Boot | None) -> _Stage:
    """The host, with 🎭 the stand-in drive if its shield is on."""
    it = host(boot=how, drive_blocks=_DRIVE_BLOCKS if shields else None)
    return _Stage(it.platform, it.cpu, it.uart, it.syscon)


def _ssd(shields: Sequence[str], how: boot.Boot | None) -> _Stage:
    """The SSD, with 🎭 a host in front of it.

    One that asks nothing of it, or with its shield on, one that says a
    host's first words to a drive.
    """
    it = ssd(host=_a_hosts_first_words if shields else idle_host, boot=how)
    return _on_a_kit(it.platform, it.ssd.cpu, it.ssd.cpu_kit)


class _TheHostGaveUp(RuntimeError):
    """🎭 A stand-in host could not do its part. The message is for the user."""


def _a_hosts_first_words() -> Steps[None]:
    """🎭 The host of the shield `socpuppet_ssd_host`, as a script.

    What a host does with a drive first, and then no more. It finds the
    drive on its PCIe link and lets it reach the host's memory. It enables
    the controller and waits for the firmware to say it is ready. It asks
    for a pair of I/O queues, which is three commands on the admin queue.
    It asks the drive how big it is, which is a fourth, answered with a
    page of data. And it writes one block of zeros at the start of the
    drive, which is the first command on an I/O queue.

    ⚠️ It waits for "ready" as long as the controller says that may take,
    which for socpuppet's frontend is a second of simulated time. An image
    that is run with the shield has that long to say so, or to be done.
    """
    try:
        nvme = yield from bring_up_the_drive()
        yield from nvme.write_blocks(first=0, data=bytes(512))
    except NvmeError as failed:
        raise _TheHostGaveUp(
            "The shield socpuppet_ssd_host is a host that brings the drive "
            f"up and writes its first block, and it could not. {failed} An "
            "image that does not answer a host is one to run without "
            "--shield socpuppet_ssd_host."
        ) from failed


def _iomgr(shields: Sequence[str], how: boot.Boot | None) -> _Stage:
    """The IO die's manager, with 🎭 a compute die that makes one round trip.

    The round trip is across the link, once the manager's firmware has
    trained it and let that die out of reset.
    """
    it = io_manager(compute=one_round_trip, boot=how)
    return _on_a_kit(it.platform, it.manager.cpu, it.manager.cpu_kit)


def _on_a_kit(platform: Platform, cpu: Placed, kit: CpuKit | None) -> _Stage:
    """The stage of a board whose CPU has the kit every 32-bit CPU has."""
    assert kit is not None  # a board described with no script has a CPU
    return _Stage(platform, cpu, kit.uart, kit.syscon)


#: The boards an image can be run on, by the names Zephyr has for them.
BOARDS = {
    "socpuppet_host": _Board(("socpuppet_host_drive",), _host),
    "socpuppet_ssd": _Board(("socpuppet_ssd_host",), _ssd),
    "socpuppet_iomgr": _Board((), _iomgr),
}
#: How many 512-byte blocks the drive of the shield `socpuppet_host_drive`
#: has.
_DRIVE_BLOCKS = 4096
#: The boot ROM's program for each kind of CPU, as `firmware/build.sh`
#: names the two it builds from `firmware/rom`.
_ROMS = {32: "rom_rv32.elf", 64: "rom_rv64.elf"}


def run(
    image: str,
    board: str,
    shields: Sequence[str],
    *,
    from_rom: bool,
    until: int,
) -> None:
    """Run the ELF file `image` on `board`, and print what it says.

    The board has `shields` on it. With `from_rom`, the CPU starts in its
    boot ROM and finds the image in the board's flash. Without, the image
    is loaded straight into RAM. Each line of the console is printed when
    it is whole. The run ends when a line gives a test framework's
    verdict, when the simulation has nothing left to do, or after `until`
    of simulated time (see `ms`). It also ends when 🎭 a stand-in that a
    shield puts beside the board cannot do its part, with what it says.

    What cannot be run ends the command with one line that says why, and
    so does a verdict that a test failed, with no line: the console has
    said it.
    """
    if board not in BOARDS:
        sys.exit(
            f"There is no board {board}. The boards are "
            f"{_listed(tuple(BOARDS))}."
        )
    taken = BOARDS[board].shields
    for shield in shields:
        if not taken:
            sys.exit(f"The board {board} takes no shield.")
        if shield not in taken:
            sys.exit(
                f"The board {board} does not take the shield {shield}. "
                f"It takes {_listed(taken)}."
            )
    try:
        program = boot_image.from_elf(image)
    except (FileNotFoundError, ValueError) as refused:
        sys.exit(str(refused))
    stage = BOARDS[board].describe(shields, boot.from_rom if from_rom else None)
    cpu = stage.cpu.component
    assert isinstance(cpu, DbtRiseCpu)  # every board here has one
    if program.xlen != cpu.xlen:
        # The first sentence is what the boot ROM would say on the console
        # (firmware/rom). It is said here before anything runs, and for an
        # image that goes straight into RAM, which no ROM would see.
        sys.exit(
            f"{program.name} is a {program.xlen}-bit image, and this is a "
            f"{cpu.xlen}-bit CPU. Build the image for {board}, or run it on "
            "the board it was built for."
        )
    platform = stage.platform
    if from_rom:
        rom_program = _firmware_directory() / _ROMS[cpu.xlen]
        if not rom_program.exists():
            sys.exit(
                f"There is no boot ROM at {rom_program}. Build it with "
                "firmware/build.sh, say where it is with "
                "SOCPUPPET_FIRMWARE_DIR, or load the image straight into "
                "RAM with --boot ram."
            )
        syscon = stage.syscon.component
        assert isinstance(syscon, SystemController)
        platform.build()
        # The ROM's program is what the CPU starts in, and the image goes
        # where the system controller tells that program to look.
        platform.load_elf(rom_program, via=stage.cpu.socket)
        platform.poke(
            syscon.boot_address, program.to_bytes(), via=stage.cpu.socket
        )
    else:
        platform.build()
        platform.load_elf(image, via=stage.cpu.socket)
    try:
        verdict = _perform(platform, stage.uart, until)
    except _TheHostGaveUp as gave_up:
        sys.exit(str(gave_up))
    if verdict is None:
        # Not a failure of the command's: an image with no test framework
        # in it never gives a verdict, and what it printed is there to be
        # judged.
        why = (
            "which is where the run was to stop (--until)"
            if platform.time >= until
            else "and the simulation has nothing left to do: the CPU is "
            "asleep, and nothing is on its way to wake it"
        )
        print(
            "socpuppet run: no verdict from a test framework in "
            f"{_in_ms(platform.time)} ms of simulated time, {why}.",
            file=sys.stderr,
        )
    elif verdict == "FAILED":
        # The console has said which test and why. The status is for a
        # script that runs one image and asks only whether it passed.
        sys.exit(1)


def _perform(
    platform: Platform, uart: PlacedUart, until: int
) -> ztest.Verdict | None:
    """Run until the console gives a verdict, printing each line as it comes.

    🎓 The verdict is the last line of a run of ztest, Zephyr's test
    framework, and is what Zephyr's own test runner, twister, judges a run
    by. Returns it, or None if there was none before `until` of simulated
    time had passed or the simulation had nothing left to do.
    """
    console = Transcript(platform, {"console": uart})
    verdicts: list[ztest.Verdict] = []
    printed = 0

    def gave_a_verdict() -> bool:
        nonlocal printed
        for line in console.lines[printed:]:
            # Flushed, because what reads this (twister, or a person) is
            # waiting for each line and will end the run on one of them.
            print(line.text, flush=True)
            if verdict := ztest.verdict_of(line.text):
                verdicts.append(verdict)
        printed = len(console.lines)
        return bool(verdicts)

    if console.run_until(gave_a_verdict, timeout=until - platform.time):
        return verdicts[0]
    # A last line that never ended was never whole, and is still said.
    unfinished = uart.output.rpartition("\n")[2]
    if unfinished:
        print(unfinished, flush=True)
    return None


def _firmware_directory() -> pathlib.Path:
    """Where `firmware/build.sh` left what it built."""
    return pathlib.Path(
        os.environ.get("SOCPUPPET_FIRMWARE_DIR", "build/firmware")
    )


def _listed(names: tuple[str, ...]) -> str:
    """Names as a sentence lists them: spam, eggs and ham."""
    *others, last = names
    return f"{', '.join(others)} and {last}" if others else last


def _in_ms(time: int) -> str:
    """A time in milliseconds, with no more digits than it needs."""
    return f"{time / ms(1):.3f}".rstrip("0").rstrip(".")
