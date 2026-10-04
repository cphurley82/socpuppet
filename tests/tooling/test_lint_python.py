"""tools/lint.py on Python sources."""


def test_when_a_python_file_has_an_unused_import_lint_fails_and_names_the_file(
    repo, lint
):
    (repo / "widget.py").write_text('"""A widget."""\n\nimport os\n')

    result = lint()

    assert result.returncode != 0
    assert "widget.py" in result.stdout
