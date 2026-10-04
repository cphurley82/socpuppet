"""What tools/lint.py prints."""


def test_when_a_linter_finds_nothing_its_name_is_printed_with_a_pass_mark(repo, lint):
    (repo / "widget.cpp").write_text("// Clean under any style.\n")

    result = lint()

    assert "✅ clang-format" in result.stdout.splitlines()


def test_when_a_linter_finds_a_problem_its_name_is_printed_with_a_fail_mark(repo, lint):
    (repo / "widget.cpp").write_text("int   answer( ){return 42;}\n")

    result = lint()

    assert "❌ clang-format" in result.stdout.splitlines()


def test_when_output_goes_to_a_terminal_the_result_line_is_colored(
    repo, lint_on_a_terminal
):
    (repo / "widget.cpp").write_text("// Clean under any style.\n")

    sent = lint_on_a_terminal()

    assert ESCAPE in result_line(sent)



def test_when_no_color_is_set_the_result_line_on_a_terminal_is_plain(
    repo, lint_on_a_terminal, monkeypatch
):
    monkeypatch.setenv("NO_COLOR", "1")
    (repo / "widget.cpp").write_text("// Clean under any style.\n")

    sent = lint_on_a_terminal()

    assert ESCAPE not in result_line(sent)


ESCAPE = "\x1b["


def result_line(output):
    """The line reporting clang-format's result."""
    (line,) = [line for line in output.splitlines() if "clang-format" in line]
    return line
