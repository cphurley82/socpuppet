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


def test_when_a_python_file_is_misformatted_lint_fails_and_names_the_file(
    repo, lint
):
    (repo / "widget.py").write_text(MISFORMATTED)

    result = lint()

    assert result.returncode != 0
    assert "widget.py" in result.stdout


def test_when_run_with_fix_a_misformatted_python_file_then_passes_lint(
    repo, lint
):
    (repo / "widget.py").write_text(MISFORMATTED)

    lint("--fix")

    assert lint().returncode == 0


def test_when_package_code_passes_a_value_of_the_wrong_type_lint_fails(
    repo, lint
):
    package = repo / "python" / "socpuppet"
    package.mkdir(parents=True)
    (package / "widget.py").write_text(
        '"""A widget."""\n'
        "\n"
        "\n"
        "def double(number: int) -> int:\n"
        '    """Twice the number."""\n'
        "    return number * 2\n"
        "\n"
        "\n"
        'ANSWER = double("21")\n'
    )

    result = lint()

    assert result.returncode != 0
    assert "widget.py:9" in result.stdout


MISFORMATTED = '"""A widget."""\n\nANSWER   =   42\n'
