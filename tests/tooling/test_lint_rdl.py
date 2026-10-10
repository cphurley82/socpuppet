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
