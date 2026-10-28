"""Python at the keyboard of Linux's shell, on 🎭 the host.

The Linux boot's exit test, `test_m20_exit.py`, brings a kernel to its
prompt on the virtio console; these are its ways of getting there, of
waiting for the prompt and of typing at it, for every test that boots
Linux.
"""

import itertools
import re

import fat_image
import socpuppet as sp
from cast import (
    FW_JUMP_BIN,
    INITRAMFS_CPIO,
    LINUX_BIN,
    MANAGER,
    ROOTFS_EXT4,
    SSD,
    UEFI_FD,
    UEFI_SHELL,
)
from console import plain
from opensbi_boots import a_host_with_opensbi, loaded_by_python
from socpuppet import ftl, gpt, linux
from socpuppet.boards.host import switched_off
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import add_ssd
from socpuppet.boards.virtio import SECTOR, Virtio

#: The shell's prompt (`socpuppet.linux.PROMPT`) as the last thing it said.
PROMPT = re.compile(linux.PROMPT.pattern + "$")
#: The same through UEFI, whose disk has the root in its second partition.
#: 🎓 The kernel's EFI stub is given no command line by the boot manager,
#: and then leaves the devicetree's `bootargs` as they are.
BOOTARGS_THROUGH_UEFI = "console=hvc0 earlycon=sbi root=/dev/vda2 rw"
#: Where UEFI's boot manager looks on a disk with no boot entry of its own:
#: the removable media path for a RISC-V 64 machine.
BOOT_PROGRAM = "EFI/BOOT/BOOTRISCV64.EFI"
#: The EFI system partition, as big as the kernel needs: 48 MiB.
ESP_SECTORS = 48 * 2048
#: RAM for UEFI and the kernel together. With 128 MiB the kernel's EFI
#: stub finds no room to move the kernel to ("Failed to relocate kernel");
#: 160 MiB is enough.
RAM_THROUGH_UEFI = 192 * 1024 * 1024
#: The prompt comes at 208 s of the CPU's time on QBox's hart, 6 s on the
#: wall, and 75 s on the wall on the interpreter: a stock kernel's own
#: initcalls are most of it, the tracing subsystem's tens of seconds among
#: them.
LONG_ENOUGH = sp.ms(400_000)
#: Through UEFI the prompt comes at 318 s of QBox's time, UEFI's boot
#: manager finding the kernel on the disk before it tries the network: 9 s
#: on the wall, and two minutes on the interpreter.
LONG_ENOUGH_THROUGH_UEFI = sp.ms(600_000)
#: How long `poweroff` may take to reach the system controller: busybox
#: stops every process and unmounts the disk first, a second or two of the
#: CPU's time.
SWITCHES_OFF_WITHIN = sp.ms(30_000)


def run_to_the_prompt(board, *, within=LONG_ENOUGH):
    """Run until Linux's shell prompts, or for `within` of simulated time.

    Gives whether it prompted.
    """
    return board.platform.run_until(
        lambda: PROMPT.search(plain(board.virtio.console.output)),
        timeout=within,
    )


def type_and_wait_for_the_prompt(board, command):
    """Type `command` and Enter at the shell, and run until it prompts again.

    Gives what the shell said in between, as plain text, without the
    command's own echo before it or the prompt after it: `linux.ask`, which
    is a TimeoutError when the shell does not prompt again.
    """
    return linux.ask(board, command)


def switch_off_at_the_prompt(board):
    """Type `poweroff`, and run until the system controller switches the CPU
    off, or for `SWITCHES_OFF_WITHIN`. Gives whether it did."""
    board.virtio.console.write("poweroff\n")
    return board.platform.run_until(
        lambda: switched_off(board), timeout=SWITCHES_OFF_WITHIN
    )


def a_host_with_linux(firmware, *, share=None, gdb_port=0, rtc_time=0):
    """A host built with the kernel and its root filesystem in place.

    🎭 The quick way, as `socpuppet.linux` boots it, from the directory
    the `firmware` fixture finds the images in, so that a missing one
    skips the test. `share` is a directory of this machine for Linux to
    mount (`mount -t 9p`), if any. With a `gdb_port`, the CPU waits for a
    debugger. `rtc_time` is what the real-time clock reads as the
    simulation starts.
    """
    return linux.host_with_linux(
        linux_images(firmware),
        share=share,
        gdb_port=gdb_port,
        rtc_time=rtc_time,
    )


def a_host_with_the_initramfs(
    firmware, *, drive_blocks=None, drive=None, manager=None
):
    """A host built with the kernel and the initramfs, its root on the
    virtio disk.

    🎭 The quick way: the initramfs sits in RAM beside the kernel, and its
    `/init` loads the kernel's NVMe modules and mounts the root
    `linux.BOOTARGS` names. `drive_blocks`, if any, is how big the host's
    drive is, and `drive` and `manager` are what `host()` adds the drive
    and the IO manager with.
    """
    rootfs = firmware(ROOTFS_EXT4).read_bytes()
    board, layout = a_host_with_opensbi(
        firmware,
        LINUX_BIN,
        virtio=Virtio(blocks=len(rootfs) // SECTOR),
        bootargs=linux.BOOTARGS,
        initrd=firmware(INITRAMFS_CPIO).read_bytes(),
        drive_blocks=drive_blocks,
        drive=drive,
        manager=manager,
    )
    board.virtio.blk.load(rootfs)
    loaded_by_python(board, layout, firmware)
    return board


def a_host_with_the_bootchain_and_the_initramfs(firmware, *, drive_blocks):
    """M8's board with Linux on the host, booted as `a_host_with_the_initramfs`.

    The IO manager and the SSD each run their own Zephyr firmware, loaded
    straight into their RAM; the manager trains the die-to-die link and
    lets the host out of reset. `drive_blocks` is how big the SSD is.
    """
    board = a_host_with_the_initramfs(
        firmware, drive_blocks=drive_blocks, drive=add_ssd, manager=add_manager
    )
    for image, cpu in (
        (MANAGER, board.manager.cpu),
        (SSD, board.drive.ssd.cpu),
    ):
        board.platform.load_elf(firmware(image), via=cpu.socket)
    return board


def a_host_with_its_root_on_the_drive(firmware, *, iommu=False):
    """M8's board, with Linux on the host and its root on the SSD.

    As `socpuppet.linux` boots it (`root="drive"`), from the directory the
    `firmware` fixture finds the images in, so that a missing one skips
    the test. With `iommu=True`, the drive is behind an IOMMU.
    """
    for image in (INITRAMFS_CPIO, MANAGER, SSD):
        firmware(image)
    return linux.host_with_linux(
        linux_images(firmware), root="drive", iommu=iommu
    )


def linux_images(firmware):
    """The directory the `firmware` fixture finds the images to boot in.

    A missing image skips the test.
    """
    for image in (FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4):
        firmware(image)
    return firmware(LINUX_BIN).parent


def a_disk_as_a_servers(firmware):
    """🎓 A disk cut up as a server's, for UEFI to boot Linux from.

    A GUID partition table with an EFI system partition, FAT, holding the
    kernel as `BOOT_PROGRAM`, which is a UEFI program too by its EFI stub;
    and the root filesystem in the second partition.
    """
    esp = fat_image.make(
        {BOOT_PROGRAM: firmware(LINUX_BIN).read_bytes()},
        sectors=ESP_SECTORS,
    )
    return gpt.make(
        [
            gpt.Partition(gpt.EFI_SYSTEM, "EFI system", esp),
            gpt.Partition(
                gpt.LINUX_FILESYSTEM,
                "root",
                firmware(ROOTFS_EXT4).read_bytes(),
            ),
        ]
    )


def a_host_with_uefi_and_linux(firmware, boot):
    """A host built with UEFI to start, and the kernel on a server's disk.

    `boot` puts OpenSBI and UEFI where the host starts them, the quick way
    or from the flash (`opensbi_boots.loaded_by_python`, `in_the_flash`).
    """
    disk = a_disk_as_a_servers(firmware)
    board, layout = a_host_with_opensbi(
        firmware,
        UEFI_FD,
        virtio=Virtio(blocks=len(disk) // SECTOR),
        bootargs=BOOTARGS_THROUGH_UEFI,
        ram=RAM_THROUGH_UEFI,
    )
    board.virtio.blk.load(disk)
    boot(board, layout, firmware)
    return board


#: What UEFI's shell runs from the drive's EFI system partition: the kernel,
#: by its EFI stub, told where its initramfs is on the same partition, and
#: its command line, root in the drive's second partition. 🎓 A kernel a
#: program starts takes its command line from what the program says, in
#: place of the devicetree's `bootargs`.
STARTUP_NSH = (
    "FS0:\r\n"
    "\\linux.efi initrd=\\initramfs.cpio console=hvc0 earlycon=sbi "
    "root=/dev/nvme0n1p2 rw\r\n"
)


def a_host_with_uefi_and_its_root_on_the_drive(firmware):
    """M8's board, UEFI starting the kernel from the drive, as a server's.

    The drive is cut up as a server's: an EFI system partition with UEFI's
    shell where the boot manager looks on a disk with no boot entry of its
    own, a `startup.nsh` for the shell to run, the kernel and the
    initramfs; and the root filesystem in the second partition.
    🎭 OpenSBI and UEFI are loaded the quick way.
    """
    esp = fat_image.make(
        {
            BOOT_PROGRAM: firmware(UEFI_SHELL).read_bytes(),
            "EFI/BOOT/startup.nsh": STARTUP_NSH.encode(),
            "linux.efi": firmware(LINUX_BIN).read_bytes(),
            "initramfs.cpio": firmware(INITRAMFS_CPIO).read_bytes(),
        },
        sectors=ESP_SECTORS,
    )
    blocks, disk = linux.disk_for_the_drive(
        [
            gpt.Partition(gpt.EFI_SYSTEM, "EFI system", esp),
            gpt.Partition(
                gpt.LINUX_FILESYSTEM, "root", firmware(ROOTFS_EXT4).read_bytes()
            ),
        ]
    )
    board, layout = a_host_with_opensbi(
        firmware,
        UEFI_FD,
        virtio=Virtio(),
        ram=RAM_THROUGH_UEFI,
        drive_blocks=blocks,
        drive=add_ssd,
        manager=add_manager,
    )
    nand = board.drive.ssd.nand
    nand.load(ftl.nand_image(disk, nand.component))
    for image, cpu in (
        (MANAGER, board.manager.cpu),
        (SSD, board.drive.ssd.cpu),
    ):
        board.platform.load_elf(firmware(image), via=cpu.socket)
    loaded_by_python(board, layout, firmware)
    return board


def messages_taken(interrupts, queue):
    """How many messages `queue`'s vector brought, on every CPU together.

    `interrupts` is Linux's /proc/interrupts: a line for each interrupt,
    its number, a count for each CPU, then what it is, its name last.
    """
    (line,) = [
        each for each in interrupts.splitlines() if each.split()[-1:] == [queue]
    ]
    counts = itertools.takewhile(str.isdigit, line.split()[1:])
    return sum(int(count) for count in counts)
