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

import datetime
import os
import pathlib
import re
from collections.abc import Sequence
from typing import Any, Literal, overload

from socpuppet import devicetree, ftl, gpt, opensbi
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.drive import BehavioralDrive
from socpuppet.boards.host import (
    MODEL,
    RAM_BASE,
    AddDrive,
    AddManager,
    Host,
    HostCpu,
    host,
)
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK, Ssd, add_ssd
from socpuppet.boards.virtio import SECTOR, Virtio
from socpuppet.time import ms

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
#: The prompt as the last thing the shell said, which is when it is ready
#: for the next command: a command's own output may quote the prompt.
_PROMPTED = re.compile(PROMPT.pattern + "$")
#: An escape sequence as the shell dresses what it prints with, to move and
#: colour a terminal: ESC, `[`, numbers and semicolons, and a letter.
_ESCAPE_SEQUENCE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
#: How long a command typed at the prompt may take to prompt again, in
#: simulated time: `uname -a` answers in under a second of the CPU's time.
ANSWERS_WITHIN = ms(10_000)
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
    trace: bool = False,
    iommu: bool = False,
    rtc_time: datetime.datetime | int = 0,
) -> Host[BehavioralDrive]: ...
@overload
def host_with_linux(
    firmware: pathlib.Path,
    *,
    cpu: HostCpu | None = None,
    share: str | os.PathLike[str] | None = None,
    gdb_port: int = 0,
    root: Literal["drive"],
    trace: bool = False,
    drive: AddDrive[Ssd] = add_ssd,
    manager: AddManager = add_manager,
    iommu: bool = False,
    rtc_time: datetime.datetime | int = 0,
) -> Host[Ssd]: ...
def host_with_linux(
    firmware: pathlib.Path,
    *,
    cpu: HostCpu | None = None,
    share: str | os.PathLike[str] | None = None,
    gdb_port: int = 0,
    root: Root = "virtio",
    trace: bool = False,
    drive: AddDrive[Ssd] = add_ssd,
    manager: AddManager = add_manager,
    iommu: bool = False,
    rtc_time: datetime.datetime | int = 0,
) -> Host[Any]:
    """A host built with Linux in place, from the images in `firmware`.

    `firmware` is the directory `firmware/build.py` left OpenSBI and Linux
    in. `cpu` is the host's CPU, as `host()` takes it, so that with none
    it is the one SOCPUPPET_CPU names. `share` is a directory of this
    machine for Linux to mount (`mount -t 9p`), if any. With a
    `gdb_port`, the CPU waits for a debugger. `root` is where the root
    filesystem is: 🎭 the virtio disk, or the drive, on M8's board. With
    `trace=True`, everything that crosses the link between the dies is
    recorded in `platform.trace`, as `host(trace=True)` records it.

    With the root on the drive, `drive` and `manager` are the functions
    `host()` describes the SSD and the IO manager with: `add_ssd` and
    `add_manager`, each a CPU running its own firmware, unless told
    otherwise. 🎭 With a script in a CPU's place
    (`functools.partial(add_ssd, firmware=scripted_firmware().script)`,
    `functools.partial(add_manager, script=scripted_manager().script)`)
    that CPU's image is neither needed nor loaded.

    With `iommu=True`, the drive is behind an IOMMU (`host(iommu=True)`),
    which Linux's own driver brings up. It needs the drive, and so the root
    on it.

    `rtc_time` is what the real-time clock reads as the simulation starts
    (`host(rtc_time=...)`), 1970 unless told otherwise, and the kernel
    sets its own clock from it as it boots, with either root.

    A missing image is a FileNotFoundError that says how to build it,
    before the simulator is built, so the process can still build another
    platform. A CPU that this build has not, or that
    the host cannot have, is a ValueError that says so.
    """
    if iommu and root != "drive":
        raise ValueError(
            "An IOMMU needs a drive to put in front of, and Linux's host has "
            "the drive only with its root on it: host_with_linux(..., "
            'root="drive", iommu=True).'
        )
    if root == "drive":
        return _with_the_root_on_the_drive(
            firmware,
            cpu=cpu,
            share=share,
            gdb_port=gdb_port,
            trace=trace,
            drive=drive,
            manager=manager,
            iommu=iommu,
            rtc_time=rtc_time,
        )
    return _with_the_root_on_virtio(
        firmware,
        cpu=cpu,
        share=share,
        gdb_port=gdb_port,
        trace=trace,
        rtc_time=rtc_time,
    )


def _with_the_root_on_virtio(
    firmware: pathlib.Path,
    *,
    cpu: HostCpu | None,
    share: str | os.PathLike[str] | None,
    gdb_port: int,
    trace: bool,
    rtc_time: datetime.datetime | int,
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
        trace=trace,
        rtc_time=rtc_time,
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
    trace: bool,
    drive: AddDrive[Ssd],
    manager: AddManager,
    iommu: bool,
    rtc_time: datetime.datetime | int,
) -> Host[Ssd]:
    """M8's board, with Linux on the host and its root on the SSD.

    The disk is a GUID partition table with the root filesystem as its
    first partition, as big as the drive: whole NAND blocks. The manager's
    image and the SSD's are loaded into the CPUs `manager` and `drive`
    describe, and 🎭 a script in a CPU's place gets none.
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
    blocks, disk = disk_for_the_drive(
        [gpt.Partition(gpt.LINUX_FILESYSTEM, "root", rootfs)]
    )
    board = host(
        cpu=cpu,
        boot=from_rom,
        sbi=True,
        drive_blocks=blocks,
        drive=drive,
        manager=manager,
        # The virtio devices stay for the console and the share. Their
        # disk is blank, and Linux sees it as /dev/vda beside the drive.
        virtio=Virtio(share=share),
        gdb_port=gdb_port,
        trace=trace,
        iommu=iommu,
        rtc_time=rtc_time,
    )
    assert board.drive is not None  # it was described with one
    assert board.manager is not None
    # Each image is looked for before anything is built, so that a missing
    # one is refused while the process can still build another platform;
    # and before dtc is asked for, so that on a machine without dtc it is
    # still the missing image that is named.
    # 🎭 A script in a CPU's place needs none.
    images = []
    if board.manager.cpu_kit is not None:
        images.append((built(firmware / MANAGER_ELF), board.manager.cpu.socket))
    if board.drive.ssd.cpu_kit is not None:
        images.append((built(firmware / SSD_ELF), board.drive.ssd.cpu.socket))
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
    nand = board.drive.ssd.nand
    nand.load(ftl.nand_image(disk, nand.component))
    for image, via in images:
        board.platform.load_elf(image, via=via)
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


def ask(board: Host[Any], command: str, *, within: int = ANSWERS_WITHIN) -> str:
    """Type `command` at Linux's shell, and give back what it answered.

    `board` is a host with Linux at its prompt on the virtio console. The
    answer is what the shell printed between the command's own echo and
    the next prompt, as plain text: the escape sequences a shell dresses
    its output with, to move and colour a terminal, are left out. A shell
    that does not prompt again within `within` of simulated time is a
    TimeoutError that names the command.
    """
    assert board.virtio is not None  # Linux's console is a virtio one
    console = board.virtio.console
    said_before = len(console.output)
    console.write(command + "\n")
    prompted = board.platform.run_until(
        lambda: (
            _PROMPTED.search(_plain(console.output[said_before:])) is not None
        ),
        timeout=within,
    )
    if not prompted:
        raise TimeoutError(
            f"The shell did not prompt again after {command!r}. It said:\n"
            + _plain(console.output[said_before:])
        )
    answer = _plain(console.output[said_before:]).partition("\n")[2]
    prompt = _PROMPTED.search(answer)
    assert prompt is not None  # it was found above
    return answer[: prompt.start()]


def _plain(text: str) -> str:
    """`text` without the escape sequences a terminal moves and colours by."""
    return _ESCAPE_SEQUENCE.sub("", text)
