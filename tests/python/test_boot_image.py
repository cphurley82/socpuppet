"""A boot image: an ELF file's program behind the header a boot ROM reads."""

import struct
import zlib

import pytest

from elf_files import elf_file
from socpuppet import boot_image
from socpuppet.regs import boot_image_header as header

RAM = 0x8000_0000
SPAM = b"Spam, spam, spam"
EGGS = b"and eggs."


def word(image, offset):
    """The 32-bit number at an offset of an image's header."""
    return struct.unpack_from("<I", image, offset)[0]


def a_program(directory, *, xlen=64, entry=RAM, segments=((RAM, SPAM),)):
    """An ELF file of one segment at the start of RAM, unless told otherwise."""
    return elf_file(directory, xlen=xlen, entry=entry, segments=list(segments))


class TestWhenAnElfFileIsWrapped:
    def test_the_image_starts_with_the_magic_number(self, tmp_path):
        image = boot_image.wrap(a_program(tmp_path))

        assert image[:4] == b"SOCP"

    @pytest.mark.parametrize("xlen", [32, 64])
    def test_the_header_says_which_kind_of_cpu_the_program_is_for(
        self, tmp_path, xlen
    ):
        image = boot_image.wrap(a_program(tmp_path, xlen=xlen))

        assert word(image, header.XLEN) == xlen

    def test_the_header_says_where_the_program_goes_and_where_it_starts(
        self, tmp_path
    ):
        image = boot_image.wrap(a_program(tmp_path, entry=RAM + 0x40))

        assert word(image, header.LOAD_ADDRESS_LOW) == RAM
        assert word(image, header.ENTRY_LOW) == RAM + 0x40

    def test_an_address_above_4_gib_has_its_upper_half_in_the_high_word(
        self, tmp_path
    ):
        high = 0x12_8000_0000
        image = boot_image.wrap(
            a_program(tmp_path, entry=high + 4, segments=[(high, SPAM)])
        )

        assert word(image, header.LOAD_ADDRESS_LOW) == 0x8000_0000
        assert word(image, header.LOAD_ADDRESS_HIGH) == 0x12
        assert word(image, header.ENTRY_LOW) == 0x8000_0004
        assert word(image, header.ENTRY_HIGH) == 0x12

    def test_the_programs_bytes_follow_the_header(self, tmp_path):
        image = boot_image.wrap(a_program(tmp_path))

        assert image[header.SIZE :] == SPAM

    def test_the_header_says_how_many_bytes_the_program_is(self, tmp_path):
        image = boot_image.wrap(a_program(tmp_path))

        assert word(image, header.LENGTH) == len(SPAM)

    def test_two_segments_are_laid_out_from_the_lower_with_zeros_between(
        self, tmp_path
    ):
        # The second segment is given first: an ELF file's are in no
        # promised order.
        image = boot_image.wrap(
            a_program(tmp_path, segments=[(RAM + 0x20, EGGS), (RAM, SPAM)])
        )

        assert image[header.SIZE :] == (SPAM + bytes(0x20 - len(SPAM)) + EGGS)
        assert word(image, header.LOAD_ADDRESS_LOW) == RAM

    def test_the_header_has_the_crc_of_the_programs_bytes(self, tmp_path):
        image = boot_image.wrap(a_program(tmp_path))

        assert word(image, header.CRC) == zlib.crc32(SPAM)

    def test_the_image_is_named_after_the_file(self, tmp_path):
        program = a_program(tmp_path).rename(tmp_path / "spam.elf")

        image = boot_image.wrap(program)

        assert the_name_in(image).rstrip(b"\0") == b"spam"

    def test_a_name_too_long_for_the_header_is_cut_to_what_fits(self, tmp_path):
        long = "a_name_that_goes_on_for_longer_than_the_header_has_room_for"
        program = a_program(tmp_path).rename(tmp_path / f"{long}.elf")

        image = boot_image.wrap(program)

        # The program is still where the header ends, and the name is as
        # much of the file's as the header has room for.
        assert image[header.SIZE :] == SPAM
        assert the_name_in(image) == long.encode()[: header.NAME_SIZE]

    def test_a_name_is_cut_between_two_characters_and_not_inside_one(
        self, tmp_path
    ):
        # "é" is two bytes of UTF-8, and the header's last byte would be
        # the first of them.
        long = "a" * (header.NAME_SIZE - 1) + "é"
        program = a_program(tmp_path).rename(tmp_path / f"{long}.elf")

        image = boot_image.wrap(program)

        assert the_name_in(image).rstrip(b"\0") == b"a" * (header.NAME_SIZE - 1)


def the_name_in(image):
    """The bytes of the name's place in an image's header."""
    return image[header.NAME : header.NAME + header.NAME_SIZE]


class TestWhenAFileThatIsNoProgramIsWrapped:
    def test_one_that_is_not_there_is_refused_by_name(self, tmp_path):
        with pytest.raises(FileNotFoundError, match=r"no_such\.elf"):
            boot_image.wrap(tmp_path / "no_such.elf")

    def test_a_program_with_nothing_to_load_is_refused_by_name(self, tmp_path):
        with pytest.raises(ValueError, match=r"program\.elf.*no bytes"):
            boot_image.wrap(a_program(tmp_path, segments=[]))

    def test_one_that_is_not_an_elf_file_is_refused_by_name(self, tmp_path):
        not_elf = tmp_path / "spam.txt"
        not_elf.write_bytes(SPAM)

        with pytest.raises(ValueError, match=r"spam\.txt"):
            boot_image.wrap(not_elf)


class TestWhenAnImageIsRead:
    def test_it_says_what_the_header_says_and_has_the_programs_bytes(
        self, tmp_path
    ):
        image = boot_image.read(
            boot_image.wrap(a_program(tmp_path, xlen=32, entry=RAM + 0x40))
        )

        # The name is the ELF file's, which the helper calls `program.elf`.
        assert image == boot_image.BootImage(
            name="program",
            xlen=32,
            load_address=RAM,
            entry=RAM + 0x40,
            payload=SPAM,
        )

    def test_an_address_above_4_gib_is_put_back_together(self, tmp_path):
        high = 0x12_8000_0000
        image = boot_image.read(
            boot_image.wrap(
                a_program(tmp_path, entry=high + 4, segments=[(high, SPAM)])
            )
        )

        assert image.load_address == high
        assert image.entry == high + 4

    def test_bytes_past_the_images_end_are_left_out(self, tmp_path):
        # A flash is read whole, and an image need not fill it.
        wrapped = boot_image.wrap(a_program(tmp_path))

        assert boot_image.read(wrapped + bytes(100)).payload == SPAM


class TestWhenBytesThatAreNoImageAreRead:
    def test_bytes_without_the_magic_number_are_refused(self):
        with pytest.raises(ValueError, match="no boot image"):
            boot_image.read(bytes(header.SIZE))

    def test_fewer_bytes_than_a_header_are_refused(self):
        with pytest.raises(ValueError, match="no boot image"):
            boot_image.read(b"SOCP")

    def test_an_image_cut_short_is_refused_and_the_error_says_by_how_much(
        self, tmp_path
    ):
        wrapped = boot_image.wrap(a_program(tmp_path))

        cut = 3
        with pytest.raises(
            ValueError,
            match=rf"program.*{len(SPAM)} bytes.*has {len(SPAM) - cut}",
        ):
            boot_image.read(wrapped[:-cut])

    def test_an_image_whose_bytes_have_changed_is_refused_by_name(
        self, tmp_path
    ):
        wrapped = bytearray(boot_image.wrap(a_program(tmp_path)))
        wrapped[header.SIZE] ^= 0x01

        with pytest.raises(ValueError, match=r"program.*CRC"):
            boot_image.read(bytes(wrapped))
