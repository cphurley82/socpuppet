"""Reading an ELF file: the program a linker wrote, as its parts.

🎓 An ELF file holds a program's bytes in segments, each with the address
it belongs at, and says where the program starts and which kind of CPU it
is for. Two things here read one: `Platform.load_elf`, which writes the
segments into a platform's memory, and `socpuppet.boot_image`, which
wraps them for a flash.
"""

from __future__ import annotations

import os
from typing import NamedTuple


class Elf(NamedTuple):
    """What an ELF file says of its program."""

    #: The file, by the name it was asked for.
    file: str
    #: Which kind of CPU the program is for: 32 or 64.
    xlen: int
    #: Where the CPU starts executing it.
    entry: int
    #: Each run of bytes to load, with the address its first byte goes at.
    segments: list[tuple[int, bytes]]


def existing(path: str | os.PathLike[str]) -> str:
    """The name of the file at `path`, refusing if there is none.

    Every loader looks first, so that each refuses a missing file in the
    same words.
    """
    file = os.fspath(path)
    if not os.path.exists(file):
        raise FileNotFoundError(
            f"There is no file at {file}. Build the firmware first, or "
            "check the path."
        )
    return file


def read(path: str | os.PathLike[str]) -> Elf:
    """The program in the ELF file at `path`.

    Raises FileNotFoundError if there is no such file, and ValueError if
    it is not an ELF file for RISC-V.
    """
    # The reader cannot tell a missing file from one that is not ELF.
    file = existing(path)
    # The reader is the simulator's, which is not loaded until wanted.
    from socpuppet import _core

    xlen, entry, segments = _core.read_elf(file)
    return Elf(file, xlen, entry, segments)
