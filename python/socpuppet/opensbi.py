"""OpenSBI's `fw_jump`, and what it starts, laid out in RAM as it expects.

🎓 OpenSBI is the machine-mode firmware a RISC-V kernel sits on. Its
`fw_jump` build is told nothing as it starts but the hart's number, in
`a0`, and the address of a devicetree, in `a1`. It jumps to a next stage
that somebody else has put in RAM, at an address fixed when it was built:
2 MiB in, on OpenSBI's generic platform, which is where Linux wants to
be. Before it jumps it copies the devicetree to 34 MiB in, out of the next
stage's way, and fixes it up there for the next stage to read.

So the two stages are laid out as one run of bytes from the start of RAM,
`fw_jump` and then the next stage 2 MiB in, with the devicetree after it:

    layout = opensbi.lay_out(fw_jump, payload, devicetree, ram=RAM_BASE)
    opensbi.load(platform, layout, rom=ROM_BASE, via=board.cpu.socket)

Or as one image in a flash, for a boot ROM to copy to RAM and start with
the devicetree's address, which is how silicon boots:

    platform.load_elf("rom_rv64.elf", via=board.cpu.socket)
    platform.poke(board.syscon.component.boot_address,
                  opensbi.flash_image(layout).to_bytes(),
                  via=board.cpu.socket)

`firmware/build.py` builds `fw_jump.bin`, and `test_payload.bin`, the
next stage OpenSBI ships.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from socpuppet.boards.boot import reset_stub
from socpuppet.boot_image import BootImage

if TYPE_CHECKING:
    from socpuppet.placed import Port
    from socpuppet.platform import Platform

#: How wide the CPU is that `fw_jump` is built for (`firmware/build.py`).
XLEN = 64
#: Where `fw_jump` jumps, from the start of RAM: FW_JUMP_OFFSET in OpenSBI's
#: `platform/generic/objects.mk`.
NEXT_STAGE_OFFSET = 0x20_0000
#: Where `fw_jump` copies the devicetree it was given before it jumps:
#: FW_JUMP_FDT_OFFSET. It grows the copy there, so RAM after it must be free.
DEVICETREE_COPY_OFFSET = 0x220_0000


class Layout(NamedTuple):
    """OpenSBI and what it starts, as one run of bytes for the start of RAM."""

    #: `fw_jump`, the next stage and the devicetree, with zeros between.
    image: bytes
    #: Where the run goes: the start of RAM, where `fw_jump` starts.
    load_address: int
    #: Where the devicetree is: what `fw_jump` is to be handed in `a1`.
    devicetree_at: int


def lay_out(
    fw_jump: bytes, next_stage: bytes, devicetree: bytes, *, ram: int
) -> Layout:
    """The three for RAM at `ram`, each where `fw_jump` wants it.

    The devicetree follows the next stage, on a boundary of 8 bytes, which
    is what a devicetree must start on. Raises ValueError if `fw_jump` is
    too big to leave room for the next stage where it jumps.
    """
    if len(fw_jump) > NEXT_STAGE_OFFSET:
        raise ValueError(
            f"fw_jump is {len(fw_jump)} bytes, and must end before 2 MiB "
            f"({NEXT_STAGE_OFFSET} bytes) into RAM, where OpenSBI's generic "
            "platform starts its next stage. Is it fw_jump.bin that was "
            "given?"
        )
    image = bytearray(fw_jump)
    image += bytes(NEXT_STAGE_OFFSET - len(image))
    image += next_stage
    image += bytes(-len(image) % 8)
    devicetree_at = ram + len(image)
    image += devicetree
    return Layout(bytes(image), ram, devicetree_at)


def load(platform: Platform, layout: Layout, *, rom: int, via: Port) -> None:
    """Put `layout` in RAM, and a start for it in the ROM at `rom`.

    🎭 The ROM is given QEMU's reset vector (`boot.reset_stub`) in place of
    a boot ROM's program, so that the CPU, which starts at `rom`, starts
    `fw_jump` with the devicetree's address. Load before the first run,
    while the ROM takes writes, and through the CPU's port, `via`.
    """
    platform.poke(
        rom,
        reset_stub(
            start=layout.load_address,
            argument=layout.devicetree_at,
            xlen=XLEN,
        ),
        via=via,
    )
    platform.poke(layout.load_address, layout.image, via=via)


def flash_image(layout: Layout) -> BootImage:
    """`layout` as one boot image, for a boot ROM to copy to RAM and start.

    The image starts `fw_jump`, where the layout starts, and its argument,
    which the ROM hands on in `a1`, is the devicetree's address. ⚠️ The
    image is the whole run of bytes, the 2 MiB to the next stage with it,
    so a ROM that checks every byte it copies takes a while over them.
    """
    return BootImage(
        name="fw_jump",
        xlen=XLEN,
        load_address=layout.load_address,
        entry=layout.load_address,
        payload=layout.image,
        argument=layout.devicetree_at,
    )
