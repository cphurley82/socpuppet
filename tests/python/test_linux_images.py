"""Linux, as `firmware/build.py` builds it, fits where `fw_jump` jumps.

🐧 A RISC-V kernel's Image starts with a header: where it wants to be
from the start of RAM (`text_offset`, 2 MiB on RISC-V, which is where
OpenSBI's generic `fw_jump` jumps), how much memory it takes once it
runs (`image_size`, more than the file, because its zeroed data follows
the bytes), and the magic `RISCV`. `fw_jump` copies the devicetree to
34 MiB in before it jumps, so a kernel that reaches past that would have
its devicetree in its own zeroed data.
"""

import struct

from cast import INITRAMFS_CPIO, LINUX_BIN, ROOTFS_EXT4
from ext4_image import file_in
from socpuppet import opensbi
from socpuppet.boards.host import RAM_SIZE

#: What the header says it is, 48 bytes in (Documentation/arch/riscv/boot-image-header.rst).
MAGIC = b"RISCV\0\0\0"
#: How each entry of an uncompressed initramfs starts: the "new" cpio format
#: with no checksums, the one the kernel unpacks
#: (Documentation/driver-api/early-userspace/buffer-format.rst).
NEWC = b"070701"


def header(image):
    """What a kernel Image's header says: (text_offset, image_size, magic)."""
    head = image.read_bytes()[:64]
    text_offset, image_size = struct.unpack_from("<QQ", head, 8)
    return text_offset, image_size, head[48:56]


class TestTheLinuxTheFirmwareBuildLeaves:
    def test_the_image_is_a_riscv_kernel_that_wants_to_be_where_fw_jump_jumps(
        self, firmware
    ):
        text_offset, _, magic = header(firmware(LINUX_BIN))
        assert magic == MAGIC
        assert text_offset == opensbi.NEXT_STAGE_OFFSET

    def test_the_kernel_in_memory_ends_before_the_devicetrees_copy(
        self, firmware
    ):
        _, image_size, _ = header(firmware(LINUX_BIN))
        kernel_ends = opensbi.NEXT_STAGE_OFFSET + image_size
        assert kernel_ends <= opensbi.DEVICETREE_COPY_OFFSET, (
            f"the kernel runs to {kernel_ends:#x} from the start of RAM, "
            f"past {opensbi.DEVICETREE_COPY_OFFSET:#x}: FW_JUMP_FDT_OFFSET "
            "in firmware/build.py and opensbi.DEVICETREE_COPY_OFFSET must move"
        )


class TestTheInitramfsTheFirmwareBuildLeaves:
    def test_it_is_an_uncompressed_cpio_the_kernel_unpacks(self, firmware):
        assert firmware(INITRAMFS_CPIO).read_bytes()[: len(NEWC)] == NEWC

    def test_it_ends_inside_the_hosts_ram(self, firmware):
        initramfs = firmware(INITRAMFS_CPIO).read_bytes()

        _, end = opensbi.initrd_span(initramfs, ram=0)

        assert end <= RAM_SIZE


#: How an ELF file starts: what the kernel runs, and what it loads.
ELF = b"\x7fELF"
#: What an ELF header says its machine is, 18 bytes in, for RISC-V
#: (`EM_RISCV`).
RISCV = 0xF3


class TestTheRootFilesystemTheFirmwareBuildLeaves:
    def test_it_has_dropbear_and_the_sftp_server_alpine_built_for_riscv(
        self, firmware
    ):
        # 🐧 dropbear answers ssh, and runs OpenSSH's SFTP server for scp.
        filesystem = firmware(ROOTFS_EXT4).read_bytes()

        for program in ("/usr/sbin/dropbear", "/usr/lib/ssh/sftp-server"):
            binary = file_in(filesystem, program)
            assert binary[: len(ELF)] == ELF, program
            assert struct.unpack_from("<H", binary, 18)[0] == RISCV, program
