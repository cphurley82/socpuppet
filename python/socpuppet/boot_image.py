"""Boot images: a program's bytes behind the header a boot ROM reads.

🎓 A boot ROM is a few hundred bytes that cannot be changed, so it cannot
read an ELF file, the format a linker writes. An image is what is left of
an ELF once the reading has been done: where the bytes go in memory, where
the CPU starts, and the bytes, with a sum for the ROM to check them by.

    image = boot_image.wrap("build/zephyr/zephyr.elf")
    platform.poke(BOOT_FLASH_BASE, image, via=board.cpu.socket)

Where each word of the header is comes from
`socpuppet.regs.boot_image_header`, which is generated from the same file
as the C header the ROM reads it with (`regs/boot_image_header.rdl`), so
the two cannot disagree.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import struct
import zlib

from socpuppet import elf
from socpuppet.regs import boot_image_header as header


@dataclasses.dataclass(frozen=True)
class BootImage:
    """An image: what its header says, and the program's bytes."""

    #: What the image is called, for a boot ROM to name in a refusal.
    name: str
    #: Which kind of CPU the program is for: 32 or 64.
    xlen: int
    #: Where in memory the program's first byte goes.
    load_address: int
    #: Where the CPU starts executing it.
    entry: int
    #: The program's bytes.
    payload: bytes

    def to_bytes(self) -> bytes:
        """The image as a flash holds it: the header, then the program."""
        head = bytearray(header.SIZE)
        for offset, word in (
            (header.MAGIC, header.MAGIC_NUMBER),
            (header.XLEN, self.xlen),
            (header.LOAD_ADDRESS_LOW, self.load_address & 0xFFFF_FFFF),
            (header.LOAD_ADDRESS_HIGH, self.load_address >> 32),
            (header.ENTRY_LOW, self.entry & 0xFFFF_FFFF),
            (header.ENTRY_HIGH, self.entry >> 32),
            (header.LENGTH, len(self.payload)),
            (header.CRC, zlib.crc32(self.payload)),
        ):
            struct.pack_into("<I", head, offset, word)
        name = _cut_to_fit(self.name)
        head[header.NAME : header.NAME + len(name)] = name
        return bytes(head) + self.payload


def _cut_to_fit(name: str) -> bytes:
    """A name as the header holds it: UTF-8, and no longer than its field.

    A name that is too long is cut between two characters, so that what is
    left is still text.
    """
    cut = name.encode()[: header.NAME_SIZE]
    return cut.decode(errors="ignore").encode()


def _word(data: bytes, offset: int) -> int:
    """The 32-bit number at an offset of a header."""
    (word,) = struct.unpack_from("<I", data, offset)
    return int(word)


def from_elf(path: str | os.PathLike[str]) -> BootImage:
    """The image of the program in the ELF file at `path`.

    The program's segments are laid out as they will be in memory, from
    the lowest address, with zeros where the file has a gap. The image is
    called what the file is, without its extension.
    """
    program = elf.read(path)
    if not program.segments:
        raise ValueError(
            f"{program.file} has no bytes to load: an image of it would be "
            "a header and nothing else."
        )
    base = min(address for address, _ in program.segments)
    end = max(address + len(data) for address, data in program.segments)
    payload = bytearray(end - base)
    for address, data in program.segments:
        payload[address - base : address - base + len(data)] = data
    return BootImage(
        name=pathlib.Path(program.file).stem,
        xlen=program.xlen,
        load_address=base,
        entry=program.entry,
        payload=bytes(payload),
    )


def wrap(path: str | os.PathLike[str]) -> bytes:
    """The image of the program in an ELF file, as bytes for a flash."""
    return from_elf(path).to_bytes()


def read(data: bytes) -> BootImage:
    """The image that `data` starts with, as a boot ROM would find it.

    It is what `BootImage.to_bytes()` wrote. `data` may go on past the
    image's end, as a flash does. Raises ValueError if it does not start
    with an image, or if the image is cut short or its bytes are not the
    ones its header was made for.
    """
    if len(data) < header.SIZE or _word(data, header.MAGIC) != (
        header.MAGIC_NUMBER
    ):
        raise ValueError(
            f"These {len(data)} bytes are no boot image: an image starts "
            f"with a header of {header.SIZE} bytes, and that with the four "
            "bytes `SOCP`."
        )
    name = (
        data[header.NAME : header.NAME + header.NAME_SIZE]
        .rstrip(b"\0")
        .decode()
    )
    length = _word(data, header.LENGTH)
    payload = data[header.SIZE : header.SIZE + length]
    if len(payload) < length:
        raise ValueError(
            f"The boot image `{name}` says it is {length} bytes and has "
            f"{len(payload)}: it has been cut short."
        )
    crc = _word(data, header.CRC)
    if zlib.crc32(payload) != crc:
        raise ValueError(
            f"The boot image `{name}` has a CRC of {crc:#010x} in its "
            f"header, and its bytes come to {zlib.crc32(payload):#010x}: "
            "they are not the ones the header was made for."
        )
    return BootImage(
        name=name,
        xlen=_word(data, header.XLEN),
        load_address=_word(data, header.LOAD_ADDRESS_LOW)
        | (_word(data, header.LOAD_ADDRESS_HIGH) << 32),
        entry=_word(data, header.ENTRY_LOW)
        | (_word(data, header.ENTRY_HIGH) << 32),
        payload=payload,
    )
