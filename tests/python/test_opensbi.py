"""OpenSBI's stage, laid out in RAM as its `fw_jump` expects."""

import pytest

from socpuppet import opensbi

RAM = 0x8000_0000
SPAM = b"spam" * 3
EGGS = b"eggs"
#: A devicetree's first bytes, its magic number.
DEVICETREE = bytes.fromhex("d00dfeed")


class TestWhenAStageIsLaidOut:
    def test_fw_jump_is_first_and_the_next_stage_2_mib_into_ram(self):
        layout = opensbi.lay_out(SPAM, EGGS, DEVICETREE, ram=RAM)

        assert layout.image[: len(SPAM)] == SPAM
        assert layout.image[0x20_0000 : 0x20_0000 + len(EGGS)] == EGGS

    def test_the_devicetree_is_next_on_a_boundary_of_8_bytes(self):
        layout = opensbi.lay_out(SPAM, EGGS, DEVICETREE, ram=RAM)

        # The next stage ends 0x20_0004 into RAM: eight bytes on is 0x20_0008.
        assert layout.devicetree_at == RAM + 0x20_0008
        assert layout.image[0x20_0008:] == DEVICETREE


class TestWhenFwJumpWouldRunIntoTheNextStage:
    def test_the_stage_is_refused_and_the_error_says_how_big_each_is(self):
        with pytest.raises(ValueError, match=r"2097153 bytes.*2 MiB"):
            opensbi.lay_out(bytes(0x20_0001), EGGS, DEVICETREE, ram=RAM)
