"""tools/lint.py on C++ sources."""


def test_when_a_cpp_file_is_misformatted_lint_fails_and_names_the_file(repo, lint):
    (repo / "widget.cpp").write_text("int   answer( ){return 42;}\n")

    result = lint()

    assert result.returncode != 0
    assert "widget.cpp" in result.stdout


def test_when_run_with_fix_a_misformatted_cpp_file_then_passes_lint(repo, lint):
    (repo / "widget.cpp").write_text("int   answer( ){return 42;}\n")

    lint("--fix")

    assert lint().returncode == 0
