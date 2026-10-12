"""Run one Zephyr image on a socpuppet board and print its console.

This is what twister invokes, through `bin/socpuppet-run`, when a board's
`board.cmake` says its emulator is `custom`. Twister reads the lines this
prints and judges them (ztest's `PROJECT EXECUTION SUCCESSFUL`, or a
console regex), then ends the process. So the job here is small: describe
the board, give the CPU its image, and let the console out a whole line
at a time as the simulation runs.

    run.py zephyr.elf --board socpuppet_host [--shield socpuppet_host_drive]
           [--boot rom|ram] [--until MS]

The image goes in the way a board boots: from a ROM and a flash by default,
because a test that resets its CPU (Zephyr's watchdog test does) only
survives the reset when something reloads the image, and that is what a
boot ROM is for. `--boot ram` is the quick tier, Python's loader.

The ROM's programs are built by firmware/build.sh, and are looked for in
`SOCPUPPET_FIRMWARE_DIR` (default: build/firmware).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import socpuppet as sp
from socpuppet import boot_image
from socpuppet.boards.boot import from_rom
from socpuppet.boards.host import host
from socpuppet.boards.io_manager import io_manager, one_round_trip
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd

BOARDS = ("socpuppet_host", "socpuppet_ssd", "socpuppet_iomgr")
SHIELDS = ("socpuppet_host_drive",)
#: What the ztest harness ends on. Not `TESTSUITE ... succeeded`: a suite
#: that expects a reboot runs more than once before its verdict.
VERDICT = "PROJECT EXECUTION"
#: Simulated time between looks at the console.
SLICE = sp.ms(1)
ROMS = {32: "rom_rv32.elf", 64: "rom_rv64.elf"}


def describe(board: str, shields: list[str], boot):
    """The board's description: platform, CPU, console, syscon and ROM."""
    if board == "socpuppet_host":
        if shields == ["socpuppet_host_drive"]:
            it = host(drive_blocks=4096, boot=boot)
        elif shields:
            sys.exit(f"{board} takes the shield {SHIELDS[0]} and no other")
        else:
            it = host(boot=boot)
        return it.platform, it.cpu, it.uart, it.syscon, it.rom
    if shields:
        sys.exit(f"{board} takes no shield")
    if board == "socpuppet_ssd":
        it = ssd(host=idle_host, boot=boot)
        kit = it.ssd.cpu_kit
        return it.platform, it.ssd.cpu, kit.uart, kit.syscon, kit.rom
    if board == "socpuppet_iomgr":
        it = io_manager(compute=one_round_trip, boot=boot)
        kit = it.manager.cpu_kit
        return it.platform, it.manager.cpu, kit.uart, kit.syscon, kit.rom
    sys.exit(f"unknown board {board}; one of {', '.join(BOARDS)}")


def give(platform, image: Path, cpu, rom, syscon) -> None:
    """Put the image where the CPU will find it (cast.py's `_give`)."""
    if rom is None:
        platform.load_elf(image, via=cpu.socket)
        return
    firmware = Path(os.environ.get("SOCPUPPET_FIRMWARE_DIR", "build/firmware"))
    its_rom = firmware / ROMS[cpu.component.xlen]
    if not its_rom.exists():
        sys.exit(f"no boot ROM at {its_rom}; build it with firmware/build.sh")
    platform.load_elf(its_rom, via=cpu.socket)
    platform.poke(
        syscon.component.boot_address, boot_image.wrap(image), via=cpu.socket
    )


def stream(platform, uart, until: int) -> bool:
    """Run, printing each whole console line as it comes, until a verdict."""
    heard = 0
    verdict = False

    def listen() -> bool:
        nonlocal heard, verdict
        output = uart.output
        whole = output.rfind("\n") + 1
        for text in output[heard:whole].splitlines():
            print(text, flush=True)
            verdict = verdict or VERDICT in text
        heard = whole
        return verdict

    while platform.time < until and not listen():
        platform.run(SLICE)
        if platform.native().picoseconds_to_next_activity() is None:
            break
    if verdict:
        platform.run(SLICE)
        listen()
    tail = uart.output[heard:]
    if tail:
        print(tail, flush=True)
    return verdict


def main(arguments: list[str] | None = None) -> None:
    """Run the image named on the command line and print its console."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("image", type=Path, help="the Zephyr image, an ELF")
    parser.add_argument("--board", required=True, choices=BOARDS)
    parser.add_argument(
        "--shield", action="append", default=[], choices=SHIELDS
    )
    parser.add_argument("--boot", choices=("rom", "ram"), default="rom")
    parser.add_argument(
        "--until",
        type=int,
        default=30_000,
        help="give up after this much simulated time, in ms",
    )
    args = parser.parse_args(arguments)
    if not args.image.exists():
        sys.exit(f"no such image: {args.image}")

    boot = from_rom if args.boot == "rom" else None
    platform, cpu, uart, syscon, rom = describe(args.board, args.shield, boot)
    platform.build()
    give(platform, args.image, cpu, rom, syscon)
    if not stream(platform, uart, sp.ms(args.until)):
        # Not an error of the runner's: a sample never gives ztest's verdict,
        # and twister judges what was printed. A ztest suite that never got
        # there fails in twister's eyes by its silence.
        elapsed = platform.time / sp.ms(1)
        print(
            f"socpuppet-run: no {VERDICT} line after {elapsed:.1f} ms of"
            " simulated time",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
