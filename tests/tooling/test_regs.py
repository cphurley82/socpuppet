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
MODULE = "python/socpuppet/regs/spam.py"
PAGE = "docs/models/spam.md"


@pytest.fixture
def repo(tmp_path):
    """A directory laid out as the repo is, with the one register map.

    And with the block's page, which has a place for its table.
    """
    (tmp_path / "regs").mkdir()
    (tmp_path / "regs/spam.rdl").write_text(textwrap.dedent(SPAM))
    (tmp_path / "docs/models").mkdir(parents=True)
    (tmp_path / PAGE).write_text(
        "# Spam\n\nWords before.\n\n"
        "<!-- regs:spam start -->\n<!-- regs:spam end -->\n"
        "\nWords after.\n"
    )
    return tmp_path


def test_the_c_header_has_each_registers_offset_its_bits_and_what_it_is_told(
    repo,
):
    regs(repo, "write")

    assert (repo / HEADER).read_text() == textwrap.dedent(
        """\
        /*
         * Spam: the registers.
         *
         * A block that stands for nothing.
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


def test_the_python_module_has_each_registers_offset_its_bits_and_what_it_is_told_without_the_blocks_name_in_front(
    repo,
):
    regs(repo, "write")

    assert (repo / MODULE).read_text() == textwrap.dedent(
        '''\
        """Spam: the registers.

        A block that stands for nothing.

        Generated from regs/spam.rdl by tools/regs.py. Do not edit: change the
        register map and run `uv run python tools/lint.py --fix`.
        """

        #: How many bytes of address space the block takes.
        SIZE = 0x40

        #: What to do. Reads as zero.
        COMMAND = 0x00
        #: Fry it.
        COMMAND_FRY = 1
        #: Bake it.
        COMMAND_BAKE = 2

        #: How it went.
        STATUS = 0x04
        #: It was done.
        STATUS_DONE = 1 << 0
        #: It is being done.
        STATUS_BUSY = 1 << 2

        #: How much there is.
        LIMITS = 0x0C
        #: How many eggs.
        LIMITS_EGGS_MASK = 0x0000FFFF
        LIMITS_EGGS_SHIFT = 0
        #: How many slices.
        LIMITS_SLICES_MASK = 0xFFFF0000
        LIMITS_SLICES_SHIFT = 16

        #: The order, 8 bytes.
        ORDER = 0x20
        ORDER_SIZE = 0x08
        '''
    )


def test_the_blocks_page_gets_a_table_with_a_row_for_each_register(repo):
    regs(repo, "write")

    assert (repo / PAGE).read_text() == (
        "# Spam\n\nWords before.\n\n"
        "<!-- regs:spam start -->\n\n"
        "| Offset | Name | Access | What it is |\n"
        "| --- | --- | --- | --- |\n"
        "| `0x00` | `COMMAND` | write | What to do. Reads as zero. "
        "1 `FRY`: Fry it. 2 `BAKE`: Bake it. |\n"
        "| `0x04` | `STATUS` | read, write | How it went. "
        "Bit 0 `DONE` (write one to clear): It was done. "
        "Bit 2 `BUSY` (read only): It is being done. |\n"
        "| `0x0C` | `LIMITS` | read | How much there is. "
        "Bits 15 to 0 `EGGS`: How many eggs. "
        "Bits 31 to 16 `SLICES`: How many slices. |\n"
        "| `0x20` | `ORDER[2]` | read | The order, 8 bytes. |\n\n"
        "<!-- regs:spam end -->\n"
        "\nWords after.\n"
    )


def test_a_register_firmware_reads_and_writes_says_so_in_its_row(repo):
    (repo / "regs/spam.rdl").write_text(a_map_of_one_register())

    regs(repo, "write")

    assert "| `HAM` | read, write |" in (repo / PAGE).read_text()


def test_a_field_with_no_description_is_in_its_registers_row_by_its_bit_and_name(
    repo,
):
    (repo / "regs/spam.rdl").write_text(
        a_map_of_one_register().replace(
            "field { sw = rw; } VALUE[31:0] = 0;",
            "field { sw = rw; } EGGS[3:3] = 0;",
        )
    )

    regs(repo, "write")

    assert "| Ham. Bit 3 `EGGS`. |" in (repo / PAGE).read_text()


def test_a_block_of_more_than_256_bytes_has_its_offsets_in_three_digits(repo):
    (repo / "regs/spam.rdl").write_text(
        a_map_of_one_register()
        .replace("block_size = 0x10", "block_size = 0x200")
        .replace("HAM @ 0x0", "HAM @ 0x104")
    )

    regs(repo, "write")

    assert "#define SPAM_HAM 0x104U\n" in (repo / HEADER).read_text()
    assert "| `0x104` | `HAM` |" in (repo / PAGE).read_text()


def test_a_place_on_the_page_for_another_generators_table_is_left_as_it_is(
    repo,
):
    another = "<!-- address-map:spam start -->\n<!-- address-map:spam end -->\n"
    (repo / PAGE).write_text((repo / PAGE).read_text() + "\n" + another)

    result = regs(repo, "write")

    assert result.returncode == 0, result.stdout
    assert (repo / PAGE).read_text().endswith(another)


def test_a_place_for_the_table_of_a_block_that_was_not_named_is_left_as_it_is(
    repo,
):
    not_named = "<!-- regs:eggs start -->\n<!-- regs:eggs end -->\n"
    (repo / PAGE).write_text((repo / PAGE).read_text() + "\n" + not_named)

    result = regs(repo, "write")

    assert result.returncode == 0, result.stdout
    assert (repo / PAGE).read_text().endswith(not_named)


def test_when_a_blocks_table_starts_and_never_ends_it_is_refused_and_the_error_says_which_marker_is_missing(
    repo,
):
    (repo / PAGE).write_text("# Spam\n\n<!-- regs:spam start -->\n\nWords.\n")

    result = regs(repo, "write")

    assert result.returncode != 0
    assert "<!-- regs:spam end -->" in result.stdout


def test_when_no_page_has_a_place_for_a_blocks_table_it_is_refused_and_the_error_says_what_to_put_where(
    repo,
):
    (repo / PAGE).write_text("# Spam\n\nWords.\n")

    result = regs(repo, "write")

    assert result.returncode != 0
    assert "<!-- regs:spam start -->" in result.stdout
    assert "docs/models" in result.stdout


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


def test_a_file_with_no_addrmap_in_it_gives_nothing_and_needs_no_page(repo):
    (repo / "regs/shared.rdl").write_text(
        "reg shared_r { field { sw = r; } VALUE[31:0]; };\n"
    )

    result = regs(repo, "write")

    assert result.returncode == 0, result.stdout
    assert not list((repo / "python").rglob("shared.*"))


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


#: A block whose registers other blocks have too, by their types, and the
#: page its own table goes on.
SHARED = """\
    `ifndef SHARED_RDL
    `define SHARED_RDL
    property block_size { type = longint unsigned; component = addrmap; };

    reg shared_command_r {
        desc = "Write a command.";
        field { sw = w; } VALUE[31:0] = 0;
    };

    addrmap shared {
        name = "Shared";
        block_size = 0x8;
        default regwidth = 32;
        shared_command_r COMMAND @ 0x4;
    };
    `endif
"""


def a_block_that_shares(repo, command_at, more=""):
    """Make `spam` a block with the shared command register at `command_at`.

    And `more`, if the block has more to say of the register than that.
    """
    (repo / "regs/shared.rdl").write_text(textwrap.dedent(SHARED))
    (repo / "docs/models/shared.md").write_text(
        "# Shared\n\n<!-- regs:shared start -->\n<!-- regs:shared end -->\n"
    )
    (repo / "regs/spam.rdl").write_text(
        textwrap.dedent(
            f"""\
            `include "shared.rdl"

            enum spam_command_e {{
                FRY = 1 {{ desc = "Fry it."; }};
            }};

            addrmap spam {{
                name = "Spam";
                block_size = 0x10;
                default regwidth = 32;
                shared_command_r COMMAND @ {command_at:#x};
                {more}
            }};
            """
        )
    )


def test_a_file_that_includes_another_blocks_file_gives_a_header_for_each_block(
    repo,
):
    a_block_that_shares(repo, command_at=0x4)

    result = regs(repo, "write")

    assert result.returncode == 0, result.stdout
    assert "#define SPAM_COMMAND 0x04U\n" in (repo / HEADER).read_text()
    assert "#define SHARED_COMMAND 0x04U\n" in (
        (repo / HEADER).with_name("shared.h").read_text()
    )


def test_what_a_block_says_of_a_shared_register_in_its_own_map_is_what_its_header_says(
    repo,
):
    a_block_that_shares(
        repo,
        command_at=0x4,
        more='COMMAND->desc = "Write what to cook.";\n'
        "    COMMAND.VALUE->encode = spam_command_e;",
    )

    regs(repo, "write")

    header = (repo / HEADER).read_text()
    assert "/* Write what to cook. */\n#define SPAM_COMMAND " in header
    assert "#define SPAM_COMMAND_FRY 1U\n" in header


def test_when_a_shared_register_is_not_where_the_block_that_shares_it_has_it_it_is_refused_and_the_error_names_both_places(
    repo,
):
    a_block_that_shares(repo, command_at=0x8)

    result = regs(repo, "write")

    assert result.returncode != 0
    assert "regs/spam.rdl" in result.stdout
    assert "COMMAND" in result.stdout
    assert "0x8" in result.stdout
    assert "regs/shared.rdl" in result.stdout
    assert "0x4" in result.stdout


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
