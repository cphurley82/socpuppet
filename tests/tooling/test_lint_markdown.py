"""tools/lint.py on Markdown."""


def test_when_a_heading_level_is_skipped_lint_fails_and_names_the_line(repo, lint):
    (repo / "notes.md").write_text(
        "# Notes\n\nSome words.\n\n### Too deep\n\nMore words.\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "notes.md:5" in result.stdout
