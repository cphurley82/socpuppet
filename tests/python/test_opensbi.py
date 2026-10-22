"""OpenSBI's stage, laid out in RAM as its `fw_jump` expects."""

import pytest

from socpuppet import opensbi

RAM = 0x8000_0000
SPAM = b"spam" * 3
EGGS = b"eggs"
HAM = b"ham" * 5
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


class TestWhenAStageIsLaidOutWithAnInitramfs:
    """🐧 An initramfs is put in RAM beside the kernel, and the devicetree
    says where: so its place is known before the devicetree is made."""

    def test_it_is_where_its_span_says(self):
        start, end = opensbi.initrd_span(HAM, ram=RAM)

        layout = opensbi.lay_out(SPAM, EGGS, DEVICETREE, ram=RAM, initrd=HAM)

        assert layout.image[start - RAM : end - RAM] == HAM

    def test_it_is_clear_of_the_room_fw_jump_copies_the_devicetree_into(self):
        start, _ = opensbi.initrd_span(HAM, ram=RAM)

        assert start >= (
            RAM + opensbi.DEVICETREE_COPY_OFFSET + opensbi.DEVICETREE_ROOM
        )

    def test_a_stage_whose_devicetree_would_land_on_it_is_refused(self):
        start, _ = opensbi.initrd_span(HAM, ram=RAM)
        # The next stage ends where the initramfs starts: its devicetree,
        # next, would be laid on the initramfs.
        too_long = bytes(start - RAM - 0x20_0000)

        with pytest.raises(ValueError, match=rf"initramfs.*{start - RAM:#x}"):
            opensbi.lay_out(SPAM, too_long, DEVICETREE, ram=RAM, initrd=HAM)


class TestWhenFwJumpWouldRunIntoTheNextStage:
    def test_the_stage_is_refused_and_the_error_says_how_big_each_is(self):
        with pytest.raises(ValueError, match=r"2097153 bytes.*2 MiB"):
            opensbi.lay_out(bytes(0x20_0001), EGGS, DEVICETREE, ram=RAM)


class TestWhenALayoutIsMadeAnImageForAFlash:
    """🎓 For a boot ROM, which copies an image to RAM and starts it with
    the argument the image's header carries in `a1`."""

    def test_the_rom_copies_it_to_the_start_of_ram_and_starts_fw_jump_there(
        self,
    ):
        layout = opensbi.lay_out(SPAM, EGGS, DEVICETREE, ram=RAM)

        image = opensbi.flash_image(layout)

        assert (image.load_address, image.entry, image.payload) == (
            RAM,
            RAM,
            layout.image,
        )

    def test_it_hands_fw_jump_the_devicetrees_address(self):
        layout = opensbi.lay_out(SPAM, EGGS, DEVICETREE, ram=RAM)

        assert opensbi.flash_image(layout).argument == layout.devicetree_at
