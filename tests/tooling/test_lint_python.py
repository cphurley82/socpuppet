"""tools/lint.py on Python sources."""


def test_when_a_python_file_has_an_unused_import_lint_fails_and_names_the_file(
    repo, lint
):
    (repo / "widget.py").write_text('"""A widget."""\n\nimport os\n')

    result = lint()

    assert result.returncode != 0
    assert "widget.py" in result.stdout


def test_when_a_public_function_has_no_docstring_lint_fails(repo, lint):
    (repo / "widget.py").write_text(
        '"""A widget."""\n\n\ndef answer():\n    return 42\n'
    )

    assert lint().returncode != 0


def test_when_run_with_fix_a_python_file_with_unsorted_imports_then_passes_lint(
    repo, lint
):
    (repo / "widget.py").write_text(
        '"""A widget."""\n\nimport sys\nimport os\n\nprint(os.sep, sys.argv)\n'
    )

    lint("--fix")

    assert lint().returncode == 0


def test_when_a_python_file_is_misformatted_lint_fails_and_names_the_file(repo, lint):
    (repo / "widget.py").write_text(MISFORMATTED)

    result = lint()

    assert result.returncode != 0
    assert "widget.py" in result.stdout


def test_when_run_with_fix_a_misformatted_python_file_then_passes_lint(repo, lint):
    (repo / "widget.py").write_text(MISFORMATTED)

    lint("--fix")

    assert lint().returncode == 0


MISFORMATTED = '"""A widget."""\n\nANSWER   =   42\n'
