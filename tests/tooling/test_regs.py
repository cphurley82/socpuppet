"""tools/regs.py, which writes what is generated from the register maps."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "regs.py"

#: A register map with one of each thing a map here has: a register that
#: is told one of a list of things, one with single bits, one with fields
#: of several bits, and one that is several words long.
SPAM = """\
    property block_size { type = longint unsigned; component = addrmap; };

    enum spam_command_e {
        FRY = 1 { desc = "Fry it."; };
        BAKE = 2 { desc = "Bake it."; };
    };

    addrmap spam {
        name = "Spam";
        desc = "A block that stands for nothing.";
        block_size = 0x40;
        default regwidth = 32;

        reg {
            desc = "What to do. Reads as zero.";
            field { sw = w; encode = spam_command_e; } VALUE[31:0] = 0;
        } COMMAND @ 0x00;

        reg {
            desc = "How it went.";
            field {
                sw = rw; onwrite = woclr; desc = "It was done.";
            } DONE[0:0] = 0;
            field { sw = r; desc = "It is being done."; } BUSY[2:2] = 0;
        } STATUS @ 0x04;

        reg {
            desc = "How much there is.";
            field { sw = r; desc = "How many eggs."; } EGGS[15:0];
            field { sw = r; desc = "How many slices."; } SLICES[31:16];
        } LIMITS @ 0x0C;

        reg {
            desc = "The order, 8 bytes.";
            field { sw = r; } WORD[31:0];
        } ORDER[2] @ 0x20 += 4;
    };
"""

HEADER = "python/socpuppet/zephyr_module/include/socpuppet/regs/spam.h"


@pytest.fixture
def repo(tmp_path):
    """A directory laid out as the repo is, with the one register map."""
    (tmp_path / "regs").mkdir()
    (tmp_path / "regs/spam.rdl").write_text(textwrap.dedent(SPAM))
    return tmp_path


def test_the_c_header_has_each_registers_offset_its_bits_and_what_it_is_told(
    repo,
):
    regs(repo, "write")

    assert (repo / HEADER).read_text() == textwrap.dedent(
        """\
        /*
         * Spam: the registers. A block that stands for nothing.
         *
         * Generated from regs/spam.rdl by tools/regs.py. Do not edit: change the
         * register map and run `uv run python tools/lint.py --fix`.
         */

        #ifndef SOCPUPPET_REGS_SPAM_H_
        #define SOCPUPPET_REGS_SPAM_H_

        /* How many bytes of address space the block takes. */
        #define SPAM_SIZE 0x40U

        /* What to do. Reads as zero. */
        #define SPAM_COMMAND      0x00U
        /* Fry it. */
        #define SPAM_COMMAND_FRY  1U
        /* Bake it. */
        #define SPAM_COMMAND_BAKE 2U

        /* How it went. */
        #define SPAM_STATUS      0x04U
        /* It was done. */
        #define SPAM_STATUS_DONE (1U << 0)
        /* It is being done. */
        #define SPAM_STATUS_BUSY (1U << 2)

        /* How much there is. */
        #define SPAM_LIMITS              0x0CU
        /* How many eggs. */
        #define SPAM_LIMITS_EGGS_MASK    0x0000FFFFU
        #define SPAM_LIMITS_EGGS_SHIFT   0U
        /* How many slices. */
        #define SPAM_LIMITS_SLICES_MASK  0xFFFF0000U
        #define SPAM_LIMITS_SLICES_SHIFT 16U

        /* The order, 8 bytes. */
        #define SPAM_ORDER      0x20U
        #define SPAM_ORDER_SIZE 0x08U

        #endif /* SOCPUPPET_REGS_SPAM_H_ */
        """
    )


def test_a_description_too_long_for_one_line_is_a_comment_of_several(repo):
    (repo / "regs/spam.rdl").write_text(
        a_map_of_one_register(
            desc="A register whose description goes on for rather longer "
            "than one line of a header has room for."
        )
    )

    regs(repo, "write")

    assert (
        "/*\n"
        " * A register whose description goes on for rather longer than one line of a\n"
        " * header has room for.\n"
        " */\n"
        "#define SPAM_HAM 0x00U\n"
    ) in (repo / HEADER).read_text()


def test_a_file_with_no_addrmap_in_it_gives_no_header(repo):
    (repo / "regs/shared.rdl").write_text(
        "reg shared_r { field { sw = r; } VALUE[31:0]; };\n"
    )

    result = regs(repo, "write")

    assert result.returncode == 0, result.stdout
    assert not (repo / HEADER).with_name("shared.h").exists()


def test_a_register_defined_in_an_included_file_is_in_the_header_of_the_block_that_has_it(
    repo,
):
    (repo / "regs/shared.rdl").write_text(
        "reg shared_r { field { sw = r; } VALUE[31:0]; };\n"
    )
    (repo / "regs/spam.rdl").write_text(
        '`include "shared.rdl"\n'
        + a_map_of_one_register().replace(
            "} HAM @ 0x0;", "} HAM @ 0x0;\n    shared_r EGGS @ 0x8;"
        )
    )

    regs(repo, "write")

    assert "#define SPAM_EGGS 0x08U\n" in (repo / HEADER).read_text()


def test_when_a_header_is_not_what_its_register_map_gives_check_fails_and_says_how_to_repair_it(
    repo,
):
    regs(repo, "write")
    (repo / "regs/spam.rdl").write_text(a_map_of_one_register())

    result = regs(repo, "check")

    assert result.returncode != 0
    assert HEADER in result.stdout
    assert "lint.py --fix" in result.stdout


def test_when_the_files_have_been_written_check_passes(repo):
    regs(repo, "write")

    assert regs(repo, "check").returncode == 0


def test_when_an_addrmap_is_not_named_after_its_file_it_is_refused_and_the_error_names_both(
    repo,
):
    (repo / "regs/spam.rdl").write_text(
        a_map_of_one_register().replace("addrmap spam", "addrmap eggs")
    )

    result = regs(repo, "write")

    assert result.returncode != 0
    assert "regs/spam.rdl" in result.stdout
    assert "eggs" in result.stdout


def test_when_a_block_does_not_say_how_big_it_is_it_is_refused_and_the_error_says_how_to(
    repo,
):
    (repo / "regs/spam.rdl").write_text(
        a_map_of_one_register().replace("    block_size = 0x10;\n", "")
    )

    result = regs(repo, "write")

    assert result.returncode != 0
    assert "regs/spam.rdl" in result.stdout
    assert "block_size = " in result.stdout


def test_when_a_register_is_outside_its_blocks_size_it_is_refused_and_the_error_names_it(
    repo,
):
    (repo / "regs/spam.rdl").write_text(
        a_map_of_one_register().replace("HAM @ 0x0", "HAM @ 0x10")
    )

    result = regs(repo, "write")

    assert result.returncode != 0
    assert "regs/spam.rdl" in result.stdout
    assert "HAM" in result.stdout


def a_map_of_one_register(desc="Ham."):
    """A register map for the block `spam`: 16 bytes, and `HAM` at 0."""
    return textwrap.dedent(
        f"""\
        property block_size {{ type = longint unsigned; component = addrmap; }};

        addrmap spam {{
            name = "Spam";
            block_size = 0x10;
            default regwidth = 32;

            reg {{
                desc = "{desc}";
                field {{ sw = rw; }} VALUE[31:0] = 0;
            }} HAM @ 0x0;
        }};
        """
    )


def regs(repo, command):
    """Run tools/regs.py on the register maps of `repo`, from its top."""
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            command,
            *(str(file.relative_to(repo)) for file in repo.glob("regs/*.rdl")),
        ],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
