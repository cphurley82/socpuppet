"""EDK2, as `firmware/build.py` builds it, is OpenSBI's next stage.

🎓 EDK2 builds a flash device image, an FD: firmware volumes one after
another, each a header and then files, padded to the size the platform's
flash description gives. The RISC-V port's first volume holds SEC, the
stage that runs first, unpacked, and the rest of EDK2 compressed. The FD
is not position-independent. SEC is linked for the address its bytes will
have when the FD sits where it was built for, and `firmware/build.py`
builds it for where `fw_jump` jumps, 2 MiB into the host's RAM, and
from a flash it is in one image with OpenSBI and the devicetree.
"""

import struct

from cast import FW_JUMP_BIN, UEFI_FD
from devicetree_compiler import needs_dtc
from socpuppet import devicetree, opensbi
from socpuppet.boards.host import RAM_BASE, host
from socpuppet.boards.manager import add_manager


class TestTheUefiImageTheFirmwareBuildLeaves:
    def test_it_starts_with_a_firmware_volume(self, firmware):
        image = firmware(UEFI_FD).read_bytes()

        assert image[SIGNATURE_AT : SIGNATURE_AT + 4] == b"_FVH"

    def test_its_first_stage_is_linked_for_where_opensbi_lays_it_out(
        self, firmware
    ):
        layout = opensbi.lay_out(
            firmware(FW_JUMP_BIN).read_bytes(),
            firmware(UEFI_FD).read_bytes(),
            devicetree=b"",
            ram=RAM_BASE,
        )

        at, linked_for = security_core(layout.image, opensbi.NEXT_STAGE_OFFSET)

        assert linked_for == layout.load_address + at

    @needs_dtc
    def test_it_fits_the_flash_with_opensbi_before_the_managers_image(
        self, firmware
    ):
        # One flash holds the host's image and, after it, the manager's.
        board = host(sbi=True, manager=add_manager)

        image = flash_image_with_opensbi(board, firmware)

        assert board.syscon.component.boot_address + len(image) <= (
            board.manager.cpu_kit.syscon.component.boot_address
        )


def flash_image_with_opensbi(board, firmware):
    """OpenSBI, EDK2 and `board`'s devicetree, as one image for its flash."""
    layout = opensbi.lay_out(
        firmware(FW_JUMP_BIN).read_bytes(),
        firmware(UEFI_FD).read_bytes(),
        devicetree.compile(
            board.platform.devicetree(dialect="linux", via=board.cpu.socket)
        ),
        ram=RAM_BASE,
    )
    return opensbi.flash_image(layout).to_bytes()


#: Where a firmware volume's header (`EFI_FIRMWARE_VOLUME_HEADER`, in EDK2's
#: PiFirmwareVolume.h) says its signature, its length, the length of the
#: header, and where an extended header is, which is zero for none.
SIGNATURE_AT, LENGTH_AT, HEADER_LENGTH_AT, EXTENDED_HEADER_AT = 40, 32, 48, 52
#: A file's header (`EFI_FFS_FILE_HEADER`) is 24 bytes, with the file's
#: type a byte 18 in and its size three bytes 20 in. A section's header is
#: its size in three bytes and its type in one.
FILE_HEADER, SECTION_HEADER = 24, 4
SECURITY_CORE, PE32 = 0x03, 0x10


def security_core(image, volume):
    """Where SEC's PE image is in `image`, and the address it is linked for.

    `volume` is where the firmware volume that holds SEC starts.
    """
    (length,) = struct.unpack_from("<Q", image, volume + LENGTH_AT)
    (header,) = struct.unpack_from("<H", image, volume + HEADER_LENGTH_AT)
    (extended,) = struct.unpack_from("<H", image, volume + EXTENDED_HEADER_AT)
    if extended:
        (extended_size,) = struct.unpack_from(
            "<I", image, volume + extended + 16
        )
        header = extended + extended_size
    each = volume + aligned(header, 8)
    while image[each + 18] != SECURITY_CORE:
        each += aligned(
            int.from_bytes(image[each + 20 : each + 23], "little"), 8
        )
        assert each < volume + length, "The volume has no SEC file"
    section = each + FILE_HEADER
    while image[section + 3] != PE32:
        size = int.from_bytes(image[section : section + 3], "little")
        section += aligned(size, 4)
    pe = section + SECTION_HEADER
    (new_header,) = struct.unpack_from("<I", image, pe + 0x3C)
    # PE32+: the optional header follows the four-byte signature and the
    # twenty bytes of the COFF header, and its image base is 24 bytes in.
    (linked_for,) = struct.unpack_from("<Q", image, pe + new_header + 48)
    return pe, linked_for


def aligned(offset, alignment):
    """`offset`, rounded up to a multiple of `alignment`."""
    return -(-offset // alignment) * alignment
