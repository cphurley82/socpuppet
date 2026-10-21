"""🐧 Linux on the host, booted the quick way (docs/linux.md).

🎭 Python puts OpenSBI's `fw_jump`, the kernel and the devicetree in RAM
where `fw_jump` expects them, and QEMU's reset vector in the ROM, and the
root filesystem on the virtio disk. The kernel's console is the virtio
console, and its first words, before that is up, are on the UART.

    board = linux.host_with_linux(pathlib.Path("build/firmware"))
    console = board.virtio.console
    board.platform.run_until(
        lambda: "socpuppet:~# " in console.output, timeout=sp.ms(400_000)
    )
"""

import os
import pathlib

from socpuppet import devicetree, opensbi
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.drive import BehavioralDrive
from socpuppet.boards.host import MODEL, RAM_BASE, Host, host
from socpuppet.boards.virtio import SECTOR, Virtio

#: The kernel, as the flat Image `fw_jump` jumps to, and its root filesystem:
#: Alpine's mini root as an ext4 image, which `firmware/build.py linux`
#: builds beside it.
LINUX_BIN = "linux.bin"
ROOTFS_EXT4 = "rootfs.ext4"
#: What the kernel is told: its console is 🎭 the virtio console, its early
#: messages go through OpenSBI's console until that is up, and its root
#: filesystem is 🎭 the virtio disk, writable.
BOOTARGS = "console=hvc0 earlycon=sbi root=/dev/vda rw"


def host_with_linux(
    firmware: pathlib.Path,
    *,
    share: str | os.PathLike[str] | None = None,
    gdb_port: int = 0,
) -> Host[BehavioralDrive]:
    """A host built with Linux in place, from the images in `firmware`.

    `firmware` is the directory `firmware/build.py` left OpenSBI and Linux
    in. `share` is a directory of this machine for Linux to mount
    (`mount -t 9p`), if any. With a `gdb_port`, the CPU waits for a
    debugger.

    A missing image is a FileNotFoundError that says how to build it,
    before anything is described.
    """
    fw_jump, kernel, rootfs = (
        _read(firmware / name)
        for name in (opensbi.FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4)
    )
    board = host(
        boot=from_rom,
        sbi=True,
        virtio=Virtio(blocks=len(rootfs) // SECTOR, share=share),
        gdb_port=gdb_port,
    )
    layout = opensbi.lay_out(
        fw_jump,
        kernel,
        devicetree.compile(
            board.platform.devicetree(
                dialect="linux", model=MODEL, bootargs=BOOTARGS
            )
        ),
        ram=RAM_BASE,
    )
    board.platform.build()
    assert board.virtio is not None  # it was described with them
    board.virtio.blk.load(rootfs)
    opensbi.load(board.platform, layout, rom=ROM_BASE, via=board.cpu.socket)
    return board


def _read(image: pathlib.Path) -> bytes:
    """The bytes of `image`, or why there are none and how to build it."""
    if not image.exists():
        raise FileNotFoundError(
            f"There is no {image}. Build OpenSBI and Linux with "
            "`uv run firmware/build.py opensbi linux`, which takes a while "
            "the first time."
        )
    return image.read_bytes()
