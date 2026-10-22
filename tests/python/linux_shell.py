"""Python at the keyboard of Linux's shell, on 🎭 the host.

The Linux boot's exit test, `test_m20_exit.py`, brings a kernel to its
prompt on the virtio console; these are its ways of getting there, of
waiting for the prompt and of typing at it, for every test that boots
Linux.
"""

import re

import fat_image
import gpt_image
import socpuppet as sp
from cast import FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4, UEFI_FD
from console import plain
from opensbi_boots import a_host_with_opensbi
from socpuppet import linux
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
#: How long a command typed at the prompt may take to prompt again: `uname`
#: answers in under a second of the CPU's time.
ANSWERS_WITHIN = sp.ms(10_000)
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
    command's own echo before it or the prompt after it.
    """
    console = board.virtio.console
    said_before = len(console.output)
    console.write(command + "\n")
    prompted = board.platform.run_until(
        lambda: PROMPT.search(plain(console.output[said_before:])),
        timeout=ANSWERS_WITHIN,
    )
    assert prompted, f"The shell did not prompt again after {command!r}"
    answer = plain(console.output[said_before:]).partition("\n")[2]
    return answer[: PROMPT.search(answer).start()]


def a_host_with_linux(firmware, *, share=None, gdb_port=0):
    """A host built with the kernel and its root filesystem in place.

    🎭 The quick way, as `socpuppet.linux` boots it, from the directory
    the `firmware` fixture finds the images in, so that a missing one
    skips the test. `share` is a directory of this machine for Linux to
    mount (`mount -t 9p`), if any. With a `gdb_port`, the CPU waits for a
    debugger.
    """
    return linux.host_with_linux(
        linux_images(firmware), share=share, gdb_port=gdb_port
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
    return gpt_image.make(
        [
            gpt_image.Partition(gpt_image.EFI_SYSTEM, "EFI system", esp),
            gpt_image.Partition(
                gpt_image.LINUX_FILESYSTEM,
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
