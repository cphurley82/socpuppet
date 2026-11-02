"""The front door: the pages a stranger reads first run as pasted.

Every example runs as pasted (docs/vision.md, the bottom rung's rules). A
block of Python on one of these pages is either a program, which imports
socpuppet and runs from the top of a checkout as it stands and prints what
the page shows under it, or an excerpt of a file in examples/, which the
prose beside it names.
"""

import pathlib
import re

import pytest

from processes import run_file

ROOT = pathlib.Path(__file__).resolve().parents[2]
#: The pages a stranger reads first.
PAGES = ("README.md",)
PYTHON = re.compile(r"^```python\n(.*?)^```\n", re.MULTILINE | re.DOTALL)
TEXT = re.compile(r"^```text\n(.*?)^```$", re.MULTILINE | re.DOTALL)
FILE = re.compile(r"examples/[\w/]+\.py")
#: A line that imports socpuppet, or something of it.
IMPORT = re.compile(r"^(?:import|from) socpuppet\b", re.MULTILINE)
#: The images a program asks for, which it finds as an installed socpuppet
#: would: built here, or fetched into the cache the first time.
IMAGE = re.compile(r"images\.find\(\s*\"([^\"]+)\"")


def is_program(code):
    """Whether a block is a whole program, and not an excerpt of one."""
    return IMPORT.search(code) is not None


def blocks(page):
    """Each block of Python on a page, with the paragraph before and after.

    The paragraph before a block introduces it; the one after is what it
    prints, or says where it is from.
    """
    text = (ROOT / page).read_text()
    found = []
    for match in PYTHON.finditer(text):
        before = text[: match.start()].rstrip("\n").rsplit("\n\n", 1)[-1]
        after = text[match.end() :].lstrip("\n").split("\n\n", 1)[0]
        found.append((match.group(1), before, after))
    return found


def front_door():
    for page in PAGES:
        for number, block in enumerate(blocks(page), start=1):
            yield pytest.param(*block, id=f"{page}-{number}")


PROGRAMS = [each for each in front_door() if is_program(each.values[0])]
EXCERPTS = [each for each in front_door() if not is_program(each.values[0])]


@pytest.mark.parametrize(("code", "before", "after"), PROGRAMS)
def test_a_block_that_imports_socpuppet_runs_as_pasted_and_prints_what_the_page_shows(
    code, before, after, tmp_path, firmware
):
    # Skipped, or failed where SOCPUPPET_REQUIRE_FIRMWARE says, as every
    # boot is when its image cannot be had (tests/python/conftest.py).
    for image in IMAGE.findall(code):
        firmware(image)
    show = tmp_path / "my_show.py"
    show.write_text(code)

    result = run_file(show, cwd=ROOT)

    assert result.returncode == 0, result.stderr
    shown = TEXT.match(after)
    assert shown, "The page shows what the program prints, in a text block"
    for line in shown.group(1).splitlines():
        assert line in result.stdout, result.stdout


@pytest.mark.parametrize(("code", "before", "after"), EXCERPTS)
def test_a_block_that_does_not_import_socpuppet_is_an_excerpt_of_a_file_named_beside_it(
    code, before, after
):
    named = FILE.findall(before + after)

    assert named, "An excerpt names the examples/ file it is from"
    for name in named:
        assert (ROOT / name).is_file(), f"{name} is named, and is not there"
