"""🧦 `socpuppet boot-image`: an ELF file wrapped for a flash."""

from elf_files import elf_file
from processes import run_socpuppet
from socpuppet import boot_image

RAM = 0x8000_0000


def a_program(directory):
    """An ELF file called `program.elf`, of one segment at the start of RAM."""
    return elf_file(
        directory, xlen=64, entry=RAM, segments=[(RAM, b"Spam, spam, spam")]
    )


class TestWhenTheBootImageCommandIsGivenAnElfFile:
    def test_it_writes_the_image_of_it_to_the_file_named(self, tmp_path):
        program = a_program(tmp_path)
        image = tmp_path / "spam.img"

        run_socpuppet("boot-image", str(program), "-o", str(image))

        assert image.read_bytes() == boot_image.wrap(program)

    def test_it_says_what_it_wrote_and_where_the_image_goes(self, tmp_path):
        program = a_program(tmp_path)
        image = tmp_path / "spam.img"

        said = run_socpuppet(
            "boot-image", str(program), "-o", str(image)
        ).stdout

        assert str(image) in said
        assert "`program`" in said
        assert "0x80000000" in said


class TestWhenTheBootImageCommandIsGivenAnArgumentForTheProgram:
    def test_the_image_carries_it(self, tmp_path):
        program = a_program(tmp_path)
        image = tmp_path / "spam.img"

        run_socpuppet(
            "boot-image",
            str(program),
            "-o",
            str(image),
            "--argument",
            "0x82200000",
        )

        assert boot_image.read(image.read_bytes()).argument == 0x8220_0000


class TestWhenTheBootImageCommandIsGivenAFileThatIsNotThere:
    def test_it_fails_in_one_line_that_names_the_file(self, tmp_path):
        result = run_socpuppet(
            "boot-image",
            str(tmp_path / "no_such.elf"),
            "-o",
            str(tmp_path / "out.img"),
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "no_such.elf" in line

    def test_it_writes_no_image(self, tmp_path):
        run_socpuppet(
            "boot-image",
            str(tmp_path / "no_such.elf"),
            "-o",
            str(tmp_path / "out.img"),
            check=False,
        )

        assert not (tmp_path / "out.img").exists()


class TestWhenTheBootImageCommandIsGivenAFileThatIsNoProgram:
    def test_it_fails_in_one_line_that_names_the_file(self, tmp_path):
        not_elf = tmp_path / "spam.txt"
        not_elf.write_bytes(b"Spam, spam, spam")

        result = run_socpuppet(
            "boot-image",
            str(not_elf),
            "-o",
            str(tmp_path / "out.img"),
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert "spam.txt" in line


class TestWhenTheBootImageCommandCannotWriteWhereItIsTold:
    def test_it_fails_in_one_line_that_names_where(self, tmp_path):
        nowhere = tmp_path / "no_such_directory" / "out.img"

        result = run_socpuppet(
            "boot-image",
            str(a_program(tmp_path)),
            "-o",
            str(nowhere),
            check=False,
        )

        assert result.returncode != 0
        [line] = result.stderr.strip().splitlines()
        assert str(nowhere) in line
