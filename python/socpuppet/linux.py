"""🐧 Linux on the host, booted the quick way (docs/linux.md).

🎭 Python puts OpenSBI's `fw_jump`, the kernel and the devicetree in RAM
where `fw_jump` expects them, and QEMU's reset vector in the ROM, and the
root filesystem on the virtio disk. The kernel's console is the virtio
console, and its first words, before that is up, are on the UART.

    board = linux.host_with_linux(pathlib.Path("build/firmware"))
    console = board.virtio.console
    board.platform.run_until(
        lambda: linux.PROMPT.search(console.output), timeout=sp.ms(400_000)
    )

Or with the root filesystem on the drive, `root="drive"`: M8's board, the
IO manager and the SSD each running their own Zephyr firmware, and the
root in the first partition of the SSD, which Python programmed as a
factory would. The kernel's NVMe driver is a module, which the initramfs
loads before it mounts the root.
"""

import os
import pathlib
import re
from collections.abc import Sequence
from typing import Any, Literal, overload

from socpuppet import devicetree, ftl, gpt, opensbi
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.drive import BehavioralDrive
from socpuppet.boards.host import MODEL, RAM_BASE, Host, HostCpu, host
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK, Ssd, add_ssd
from socpuppet.boards.virtio import SECTOR, Virtio

#: The kernel, as the flat Image `fw_jump` jumps to, and its root filesystem:
#: Alpine's mini root as an ext4 image, which `firmware/build.py linux`
#: builds beside it, with an initramfs that loads the kernel's NVMe modules
#: and mounts a root on the drive.
LINUX_BIN = "linux.bin"
ROOTFS_EXT4 = "rootfs.ext4"
INITRAMFS_CPIO = "initramfs.cpio"
#: The IO manager's firmware and the SSD's, which `firmware/build.py
#: zephyr` builds: what runs beside the host when the root is on the drive.
MANAGER_ELF = "iomgr_socpuppet_iomgr.elf"
SSD_ELF = "ssd_socpuppet_ssd.elf"
#: The kernel's console is 🎭 the virtio console, and its early messages go
#: through OpenSBI's console until that is up.
_CONSOLE = "console=hvc0 earlycon=sbi"
#: What the kernel is told: its console, and that its root filesystem is
#: 🎭 the virtio disk, writable.
BOOTARGS = f"{_CONSOLE} root=/dev/vda rw"
#: The same with the root on the drive: the first partition of the first
#: NVMe drive's first namespace, which the initramfs mounts.
BOOTARGS_ON_THE_DRIVE = f"{_CONSOLE} root=/dev/nvme0n1p1 rw"
#: How a busybox shell that is logged in as root prompts on the host, by
#: Alpine's /etc/profile: the host's name, the directory, and a hash.
PROMPT = re.compile(r"socpuppet:\S+# ")
#: Where the root filesystem can be: 🎭 the virtio disk, or the drive.
type Root = Literal["virtio", "drive"]

#: What each image is built by: the part of `firmware/build.py`.
_BUILT_BY = {
    opensbi.FW_JUMP_BIN: "opensbi linux",
    LINUX_BIN: "opensbi linux",
    ROOTFS_EXT4: "opensbi linux",
    INITRAMFS_CPIO: "opensbi linux",
    MANAGER_ELF: "zephyr",
    SSD_ELF: "zephyr",
}


@overload
def host_with_linux(
    firmware: pathlib.Path,
    *,
    cpu: HostCpu | None = None,
    share: str | os.PathLike[str] | None = None,
    gdb_port: int = 0,
    root: Literal["virtio"] = "virtio",
) -> Host[BehavioralDrive]: ...
@overload
def host_with_linux(
    firmware: pathlib.Path,
    *,
    cpu: HostCpu | None = None,
    share: str | os.PathLike[str] | None = None,
    gdb_port: int = 0,
    root: Literal["drive"],
) -> Host[Ssd]: ...
def host_with_linux(
    firmware: pathlib.Path,
    *,
    cpu: HostCpu | None = None,
    share: str | os.PathLike[str] | None = None,
    gdb_port: int = 0,
    root: Root = "virtio",
) -> Host[Any]:
    """A host built with Linux in place, from the images in `firmware`.

    `firmware` is the directory `firmware/build.py` left OpenSBI and Linux
    in. `cpu` is the host's CPU, as `host()` takes it, so that with none
    it is the one SOCPUPPET_CPU names. `share` is a directory of this
    machine for Linux to mount (`mount -t 9p`), if any. With a
    `gdb_port`, the CPU waits for a debugger. `root` is where the root
    filesystem is: 🎭 the virtio disk, or the drive, on M8's board.

    A missing image is a FileNotFoundError that says how to build it,
    before anything is described. A CPU that this build has not, or that
    the host cannot have, is a ValueError that says so.
    """
    if root == "drive":
        return _with_the_root_on_the_drive(
            firmware, cpu=cpu, share=share, gdb_port=gdb_port
        )
    return _with_the_root_on_virtio(
        firmware, cpu=cpu, share=share, gdb_port=gdb_port
    )


def _with_the_root_on_virtio(
    firmware: pathlib.Path,
    *,
    cpu: HostCpu | None,
    share: str | os.PathLike[str] | None,
    gdb_port: int,
) -> Host[BehavioralDrive]:
    """The host alone, with Linux's root on 🎭 the virtio disk."""
    fw_jump, kernel, rootfs = (
        _read(firmware / name)
        for name in (opensbi.FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4)
    )
    board = host(
        cpu=cpu,
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
                board.cpu.socket,
                dialect="linux",
                model=MODEL,
                bootargs=BOOTARGS,
            )
        ),
        ram=RAM_BASE,
    )
    board.platform.build()
    assert board.virtio is not None  # it was described with them
    board.virtio.blk.load(rootfs)
    opensbi.load(board.platform, layout, rom=ROM_BASE, via=board.cpu.socket)
    return board


def _with_the_root_on_the_drive(
    firmware: pathlib.Path,
    *,
    cpu: HostCpu | None,
    share: str | os.PathLike[str] | None,
    gdb_port: int,
) -> Host[Ssd]:
    """M8's board, with Linux on the host and its root on the SSD.

    The disk is a GUID partition table with the root filesystem as its
    first partition, as big as the drive: whole NAND blocks.
    """
    fw_jump, kernel, rootfs, initramfs = (
        _read(firmware / name)
        for name in (
            opensbi.FW_JUMP_BIN,
            LINUX_BIN,
            ROOTFS_EXT4,
            INITRAMFS_CPIO,
        )
    )
    manager, ssd = (built(firmware / name) for name in (MANAGER_ELF, SSD_ELF))
    blocks, disk = disk_for_the_drive(
        [gpt.Partition(gpt.LINUX_FILESYSTEM, "root", rootfs)]
    )
    board = host(
        cpu=cpu,
        boot=from_rom,
        sbi=True,
        drive_blocks=blocks,
        drive=add_ssd,
        manager=add_manager,
        # The virtio devices stay for the console and the share. Their
        # disk is blank, and Linux sees it as /dev/vda beside the drive.
        virtio=Virtio(share=share),
        gdb_port=gdb_port,
    )
    layout = opensbi.lay_out(
        fw_jump,
        kernel,
        devicetree.compile(
            board.platform.devicetree(
                board.cpu.socket,
                dialect="linux",
                model=MODEL,
                bootargs=BOOTARGS_ON_THE_DRIVE,
                initrd=opensbi.initrd_span(initramfs, ram=RAM_BASE),
            )
        ),
        ram=RAM_BASE,
        initrd=initramfs,
    )
    board.platform.build()
    assert board.drive is not None  # it was described with one
    assert board.manager is not None
    nand = board.drive.ssd.nand
    nand.load(ftl.nand_image(disk, nand.component))
    board.platform.load_elf(manager, via=board.manager.cpu.socket)
    board.platform.load_elf(ssd, via=board.drive.ssd.cpu.socket)
    opensbi.load(board.platform, layout, rom=ROM_BASE, via=board.cpu.socket)
    return board


def disk_for_the_drive(
    partitions: Sequence[gpt.Partition],
) -> tuple[int, bytes]:
    """A disk of `partitions` for the SSD: how many blocks, and its bytes.

    The drive is whole NAND blocks, as `add_ssd` describes it, so the disk
    is `gpt.size_of` the partitions rounded up to those, and as big as the
    drive: the partition table's copy is then in the drive's last sectors,
    where tools look for it. `host(drive_blocks=...)` takes the first, and
    `ftl.nand_image` makes the NAND's image of the second.
    """
    blocks = gpt.size_of(partitions)
    blocks += -blocks % DRIVE_BLOCKS_PER_NAND_BLOCK
    return blocks, gpt.make(partitions, sectors=blocks)


def _read(image: pathlib.Path) -> bytes:
    """The bytes of `image`, or why there are none and how to build it."""
    return built(image).read_bytes()


def built(image: pathlib.Path) -> pathlib.Path:
    """`image`, if `firmware/build.py` has built it.

    Or else a FileNotFoundError that says how to build it.
    """
    if not image.exists():
        raise FileNotFoundError(
            f"There is no {image}. Build it with `uv run firmware/build.py "
            f"{_BUILT_BY[image.name]}`, which takes a while the first time."
        )
    return image
