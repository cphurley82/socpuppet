"""tools/lint.py on Markdown."""


def test_when_a_heading_level_is_skipped_lint_fails_and_names_the_line(
    repo, lint
):
    (repo / "notes.md").write_text(
        "# Notes\n\nSome words.\n\n### Too deep\n\nMore words.\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "notes.md:5" in result.stdout


def test_when_a_paragraph_is_one_300_column_line_lint_passes(repo, lint):
    paragraph = ("word " * 60).strip()
    (repo / "notes.md").write_text(f"# Notes\n\n{paragraph}\n")

    assert lint().returncode == 0


def test_when_claude_md_only_includes_another_file_lint_passes(repo, lint):
    (repo / "CLAUDE.md").write_text("@AGENTS.md\n")

    assert lint().returncode == 0
