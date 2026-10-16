"""OpenSBI, as `firmware/build.py` builds it, fits the host's RAM.

🎓 OpenSBI's `fw_jump` runs first in RAM and jumps to the next stage at
an address fixed when it is built: 2 MiB in, on the generic platform.
`test_payload` is a next stage that OpenSBI ships, and is linked there.
OpenSBI runs wherever it is put, but its ELF file says where it was built
for, and that is where Python loads it from.
"""

from cast import FW_JUMP, FW_JUMP_BIN, TEST_PAYLOAD
from socpuppet import elf
from socpuppet.boards import host

#: Where the generic platform's `fw_jump` expects the next stage, from the
#: start of RAM (FW_JUMP_OFFSET in OpenSBI's platform/generic/objects.mk).
NEXT_STAGE = 0x20_0000


class TestTheOpenSbiTheFirmwareBuildLeaves:
    def test_fw_jump_is_a_64_bit_image_that_starts_at_the_start_of_ram(
        self, firmware
    ):
        image = elf.read(firmware(FW_JUMP))
        assert (image.xlen, image.entry) == (64, host.RAM_BASE)

    def test_the_test_payload_starts_where_fw_jump_jumps(self, firmware):
        image = elf.read(firmware(TEST_PAYLOAD))
        assert image.entry == host.RAM_BASE + NEXT_STAGE

    def test_fw_jumps_bytes_end_before_the_next_stage(self, firmware):
        assert firmware(FW_JUMP_BIN).stat().st_size < NEXT_STAGE
