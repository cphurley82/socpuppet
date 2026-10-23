"""🐧 `socpuppet drive`: a drive, built and put on this machine's own bus.

The drive is the SSD with its Zephyr firmware, or 🎭 the behavioral
drive (`socpuppet.boards.drive` describes that one), and its host is this
machine: its own Linux, through pciem (`socpuppet.boards.real_host`).
Linux's `nvme` driver binds it as it would a card in a slot, and `lsblk`
lists it, for as long as its platform is pumped.

    board = drive.on_this_machine(pathlib.Path("build/firmware"))
    pump(board.platform, far_ends=[board.host], until=...)

Once it is there, `socpuppet.boards.real_host.puppet_function` says where.
"""

import pathlib
from typing import Literal

from socpuppet import linux
from socpuppet.boards.real_host import (
    BehavioralDriveBoard,
    behavioral_drive,
    this_machine,
)
from socpuppet.boards.ssd import RealHostSsdBoard, ssd

#: Which drive it is: the SSD with its Zephyr firmware, or 🎭 the
#: behavioral drive, which has no CPU or firmware.
type Firmware = Literal["zephyr", "behavioral"]
#: How big the drive is, unless asked otherwise: 64 MiB, in 512-byte
#: blocks.
BLOCKS = 131072


def on_this_machine(
    firmware_directory: pathlib.Path,
    *,
    firmware: Firmware = "zephyr",
    blocks: int = BLOCKS,
) -> RealHostSsdBoard | BehavioralDriveBoard:
    """The drive, built, with its firmware loaded, on this machine's bus.

    `firmware_directory` is where `firmware/build.py` left the SSD's
    firmware. An image that is not there is a FileNotFoundError that says
    how to build it, before anything is described, and a build of
    socpuppet without pciem a ValueError that says how to get one.
    ⚠️ From here the platform has to be pumped, or Linux waits on a drive
    that does not answer.
    """
    board: RealHostSsdBoard | BehavioralDriveBoard
    if firmware == "behavioral":
        board = behavioral_drive(blocks=blocks)
        board.platform.build()
    else:
        image = linux.built(firmware_directory / linux.SSD_ELF)
        board = ssd(host=this_machine, blocks=blocks)
        board.platform.build()
        board.platform.load_elf(image, via=board.ssd.cpu.socket)
    board.host.start()
    return board
