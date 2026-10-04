"""What tools/lint.py prints."""


def test_when_a_linter_finds_nothing_its_name_is_printed_with_a_pass_mark(repo, lint):
    (repo / "widget.cpp").write_text("// Clean under any style.\n")

    result = lint()

    assert "✅ clang-format" in result.stdout.splitlines()
