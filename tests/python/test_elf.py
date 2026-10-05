"""Loading a program image (an ELF file) into a platform's memory."""

import pytest

import socpuppet as sp
from elf_files import elf_file

RAM_BASE = 0x8000_0000


def cpu_and_ram(*, xlen=64, reset_vector=RAM_BASE):
    """A CPU with a RAM at RAM_BASE, built."""
    platform = sp.Platform()
    cpu = platform.add(
        "cpu", sp.DbtRiseCpu(xlen=xlen, reset_vector=reset_vector)
    )
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=0x4000))
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    platform.build()
    return platform


@pytest.mark.platform
class TestWhenAnElfImageIsLoaded:
    def test_each_segment_lands_at_its_address(self, tmp_path):
        image = elf_file(
            tmp_path,
            xlen=64,
            entry=0x8000_0000,
            segments=[
                (0x8000_0000, (0x11111111).to_bytes(4, "little")),
                (0x8000_1000, (0x22222222).to_bytes(4, "little")),
            ],
        )
        platform = cpu_and_ram()

        platform.load_elf(image)

        assert platform.peek32(0x8000_0000) == 0x11111111
        assert platform.peek32(0x8000_1000) == 0x22222222


@pytest.mark.platform
class TestWhenAnImagesWordSizeIsNotTheCpus:
    @pytest.mark.parametrize(("image_xlen", "cpu_xlen"), [(32, 64), (64, 32)])
    def test_loading_is_refused_and_the_error_says_which_is_which(
        self, tmp_path, image_xlen, cpu_xlen
    ):
        image = elf_file(
            tmp_path,
            xlen=image_xlen,
            entry=0x8000_0000,
            segments=[(0x8000_0000, b"code")],
        )
        platform = cpu_and_ram(xlen=cpu_xlen)

        with pytest.raises(
            ValueError, match=rf"{image_xlen}-bit image.*{cpu_xlen}-bit CPU"
        ):
            platform.load_elf(image)


@pytest.mark.platform
class TestWhenAnImageDoesNotStartAtTheCpusResetVector:
    def test_loading_is_refused_and_the_error_gives_both_addresses(
        self, tmp_path
    ):
        image = elf_file(
            tmp_path,
            xlen=64,
            entry=0x8000_0040,
            segments=[(0x8000_0000, b"code")],
        )
        platform = cpu_and_ram(reset_vector=0x8000_0000)

        with pytest.raises(
            ValueError, match=r"starts at 0x80000040.*reset vector.*0x80000000"
        ):
            platform.load_elf(image)


@pytest.mark.platform
class TestWhenASegmentDoesNotFitInAnyMemory:
    def test_the_error_names_the_file_and_where_the_segment_belongs(
        self, tmp_path
    ):
        image = elf_file(
            tmp_path,
            xlen=64,
            entry=0x8000_0000,
            segments=[(0x8000_0000, b"code"), (0x9000_0000, b"more")],
        )
        platform = cpu_and_ram()

        with pytest.raises(LookupError, match=r"program\.elf.*0x90000000"):
            platform.load_elf(image)


@pytest.mark.platform
class TestWhenTheImageFileDoesNotExist:
    def test_loading_is_refused_and_the_error_names_the_file(self, tmp_path):
        platform = cpu_and_ram()

        with pytest.raises(FileNotFoundError, match=r"no_such_program\.elf"):
            platform.load_elf(tmp_path / "no_such_program.elf")
