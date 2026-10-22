"""The firmware a host's CPUs are given, and the one way a test gives it.

A host has up to three CPUs, each with an image of its own: the host's,
the IO die's manager's, and the SSD's. A test says which image each has,
and `boot` builds the platform and puts every image where its CPU will
find it. Where that is depends on how the board was described:

- 🎭 With no `boot`, Python is the stand-in for a boot ROM: the image is
  written straight into its CPU's RAM before anything runs.
- With `boot=from_rom`, the CPU has a ROM, which is given the boot ROM's
  program, and the image goes into the flash, where the CPU's system
  controller tells the ROM to look.
"""

import functools

import socpuppet as sp
from disk_access import IMAGE as DISK_TEST
from manager_firmware import IMAGE as MANAGER
from socpuppet import boot_image, linux, opensbi
from socpuppet.boards.boot import from_rom
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import add_ssd
from ssd_zephyr_firmware import IMAGE as SSD

__all__ = [
    "DISK_TEST",
    "FROM_THEIR_ROMS",
    "FW_JUMP",
    "FW_JUMP_BIN",
    "GREETING",
    "HELLO_WORLD",
    "INITRAMFS_CPIO",
    "LINUX",
    "LINUX_BIN",
    "LINUX_MAP",
    "LOADED_BY_PYTHON",
    "MANAGER",
    "ROM_FOR_A_32_BIT_CPU",
    "ROM_FOR_A_64_BIT_CPU",
    "ROOTFS_EXT4",
    "SBI_PAYLOAD_BIN",
    "SHELL",
    "SSD",
    "SYNCHRONIZATION",
    "TEST_PAYLOAD",
    "TEST_PAYLOAD_BIN",
    "UEFI_FD",
    "boot",
]

#: Zephyr's own samples, built for the board `socpuppet_host`.
HELLO_WORLD = "hello_world_socpuppet_host.elf"
SYNCHRONIZATION = "synchronization_socpuppet_host.elf"
SHELL = "shell_module_socpuppet_host.elf"
#: How the shell prompts, by the sample's configuration, and how its answer
#: to `kernel version` starts.
SHELL_PROMPT = "uart:~$ "
SHELL_VERSION = "Zephyr version"
#: What `hello_world` prints.
GREETING = "Hello World! socpuppet_host"
#: The boot ROM's program (firmware/rom), built for each kind of CPU.
ROM_FOR_A_64_BIT_CPU = "rom_rv64.elf"
ROM_FOR_A_32_BIT_CPU = "rom_rv32.elf"
#: OpenSBI (firmware/build.py): `fw_jump`, the machine-mode firmware a
#: kernel sits on, as an ELF file and as its bytes; and `test_payload`, the
#: supervisor-mode program OpenSBI ships for it to jump to.
FW_JUMP = "fw_jump.elf"
FW_JUMP_BIN = opensbi.FW_JUMP_BIN
TEST_PAYLOAD = "test_payload.elf"
TEST_PAYLOAD_BIN = "test_payload.bin"
#: A next stage for OpenSBI of socpuppet's own (firmware/sbi_payload), which
#: makes the calls of SBI's that `test_payload` does not.
SBI_PAYLOAD_BIN = "sbi_payload.bin"
#: EDK2's RISC-V port (firmware/build.py): UEFI, as a flash device image
#: built to run where `fw_jump` jumps.
UEFI_FD = "uefi.fd"
#: 🐧 Linux (firmware/build.py): the kernel as the flat Image `fw_jump`
#: jumps to, as vmlinux with its symbols, and as its System.map.
LINUX_BIN = linux.LINUX_BIN
LINUX = "linux.elf"
LINUX_MAP = "linux.map"
#: The kernel's root filesystem (firmware/build.py): Alpine's mini root with
#: an inittab of ours, as an ext4 image for 🎭 the virtio disk.
ROOTFS_EXT4 = linux.ROOTFS_EXT4
#: What loads the kernel's NVMe modules and mounts a root on the drive
#: (firmware/build.py): an initramfs, as an uncompressed cpio.
INITRAMFS_CPIO = linux.INITRAMFS_CPIO


#: The two ways the three CPUs of a host get their firmware, as what
#: `host()` is described with for each: `host(**FROM_THEIR_ROMS)`.
LOADED_BY_PYTHON = {"manager": add_manager, "drive": add_ssd}
FROM_THEIR_ROMS = {
    "boot": from_rom,
    "manager": functools.partial(add_manager, boot=from_rom),
    "drive": functools.partial(add_ssd, boot=from_rom),
}


def boot(board, firmware, *, host, manager=None, ssd=None):
    """Build a host and give an image to each CPU that is to have one.

    `firmware` is the fixture that finds an image by its file's name. A
    manager or an SSD that is given no image is one with no CPU: 🎭 a
    script, a stand-in, or none at all.

    Returns the story the consoles of those CPUs tell, as a transcript
    that has heard nothing yet.
    """
    platform = board.platform
    platform.build()
    _give(
        platform, firmware(host), board.cpu, board.rom, board.syscon, firmware
    )
    consoles = {}
    if manager is not None:
        kit = board.manager.cpu_kit
        _give(
            platform,
            firmware(manager),
            board.manager.cpu,
            kit.rom,
            kit.syscon,
            firmware,
        )
        consoles["manager"] = kit.uart
    if ssd is not None:
        kit = board.drive.ssd.cpu_kit
        _give(
            platform,
            firmware(ssd),
            board.drive.ssd.cpu,
            kit.rom,
            kit.syscon,
            firmware,
        )
        consoles["ssd"] = kit.uart
    consoles["host"] = board.uart
    return sp.Transcript(platform, consoles)


def _give(platform, image, cpu, rom, syscon, firmware):
    """Put an image where `cpu` will find it, which depends on how it boots.

    ⚠️ A host can have three bus masters, so everything is loaded through
    the CPU whose firmware it is.
    """
    if rom is None:
        platform.load_elf(image, via=cpu.socket)
        return
    its_rom = {
        32: ROM_FOR_A_32_BIT_CPU,
        64: ROM_FOR_A_64_BIT_CPU,
    }[cpu.component.xlen]
    platform.load_elf(firmware(its_rom), via=cpu.socket)
    platform.poke(
        syscon.component.boot_address, boot_image.wrap(image), via=cpu.socket
    )
