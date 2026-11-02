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


def test_when_run_with_fix_a_list_with_no_blank_line_before_it_then_passes_lint(
    repo, lint
):
    (repo / "notes.md").write_text("# Notes\n\nTwo things:\n- one\n- two\n")

    lint("--fix")

    assert "Two things:\n\n- one\n" in (repo / "notes.md").read_text()
    assert lint().returncode == 0


def test_when_a_link_names_a_page_that_is_not_there_lint_fails_and_names_the_line(
    repo, lint
):
    (repo / "notes.md").write_text(
        "# Notes\n\nSee [the plan](plan.md).\n\nMore words.\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "notes.md:3" in result.stdout


def test_when_a_link_names_a_heading_another_page_does_not_have_lint_fails_and_names_the_line(
    repo, lint
):
    (repo / "plan.md").write_text("# The plan\n\n## The aims\n\nWords.\n")
    (repo / "notes.md").write_text(
        "# Notes\n\nSee [the gate](plan.md#the-release-gate).\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "notes.md:3" in result.stdout
