"""tools/lint.py on SystemRDL, which is what register maps are written in."""


def test_when_a_register_description_does_not_compile_lint_fails_and_names_the_line(
    repo, lint
):
    (repo / "regs").mkdir()
    (repo / "regs/spam.rdl").write_text(
        "addrmap spam {\n    reg { field {} EGGS[0:0] } HAM @ 0x0;\n};\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "❌ systemrdl" in result.stdout
    assert "regs/spam.rdl:2" in result.stdout


# A register map with single bits, a field of several, and descriptions
# short and long: what the header generated from it has to lay out.
SPAM = """\
property block_size { type = longint unsigned; component = addrmap; };

addrmap spam {
    name = "Spam";
    block_size = 0x10;
    default regwidth = 32;

    reg {
        desc = "A register whose description goes on for rather longer than one line of a header has room for, and then some.";
        field { sw = rw; onwrite = woclr; desc = "Done."; } DONE[0:0] = 0;
        field { sw = r; desc = "How many eggs."; } EGGS[31:16];
    } HAM @ 0x0;
};
"""


def test_when_run_with_fix_what_a_register_map_gives_is_written_and_then_passes_lint(
    repo, lint, zephyrs_style
):
    (repo / "regs").mkdir()
    (repo / "regs/spam.rdl").write_text(SPAM)
    (repo / "docs/models").mkdir(parents=True)
    (repo / "docs/models/spam.md").write_text(
        "# Spam\n\n<!-- regs:spam start -->\n<!-- regs:spam end -->\n"
    )

    lint("--fix")

    # A C header, a Python module and a table in the block's page: each
    # is held to its own language's rules by the linters that come after.
    header = "python/socpuppet/zephyr_module/include/socpuppet/regs/spam.h"
    assert (repo / header).exists()
    assert (repo / "python/socpuppet/regs/spam.py").exists()
    assert "| Offset |" in (repo / "docs/models/spam.md").read_text()
    assert lint().returncode == 0, lint().stdout
