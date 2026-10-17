"""A host that boots OpenSBI and the stage after it, either way it can.

🎭 The quick way: Python puts `fw_jump`, the next stage and the devicetree
in RAM where `fw_jump` expects them, and QEMU's reset vector in the ROM
hands `fw_jump` the hart's number and the devicetree's address. And the
way silicon boots: the three are one image in the flash, which the boot
ROM copies to RAM, checks, and starts with the devicetree's address from
the image's header. The OpenSBI tests boot its payloads both ways, and the
UEFI tests boot EDK2.
"""

from cast import FW_JUMP_BIN, ROM_FOR_A_64_BIT_CPU
from socpuppet import devicetree, opensbi
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.host import RAM_BASE, host

#: What the devicetree names the board, which OpenSBI's banner repeats.
MODEL = "socpuppet host"


def a_host_with_opensbi(firmware, payload, *, virtio=None):
    """A host described for OpenSBI and built, and OpenSBI's layout for it.

    `payload` is the file of the stage OpenSBI is to start. `virtio` is
    what the host's virtio devices are told, if it is to have them
    (`socpuppet.boards.virtio.Virtio`).
    """
    board = host(boot=from_rom, sbi=True, virtio=virtio)
    layout = opensbi.lay_out(
        firmware(FW_JUMP_BIN).read_bytes(),
        firmware(payload).read_bytes(),
        devicetree.compile(
            board.platform.devicetree(dialect="linux", model=MODEL)
        ),
        ram=RAM_BASE,
    )
    board.platform.build()
    return board, layout


def loaded_by_python(board, layout, firmware):
    """🎭 Put `layout` in the host's RAM, and QEMU's reset vector in its ROM."""
    opensbi.load(board.platform, layout, rom=ROM_BASE, via=board.cpu.socket)


def in_the_flash(board, layout, firmware):
    """Load the host's ROM, and `layout` as one image in its flash.

    Gives the image.
    """
    image = opensbi.flash_image(layout)
    board.platform.load_elf(
        firmware(ROM_FOR_A_64_BIT_CPU), via=board.cpu.socket
    )
    board.platform.poke(
        board.syscon.component.boot_address,
        image.to_bytes(),
        via=board.cpu.socket,
    )
    return image
