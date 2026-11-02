"""tools/lint.py read as a stranger reads the tree: no names or dates of ours."""

import pytest


def test_when_a_page_names_one_of_the_projects_machines_lint_fails_and_names_the_place(
    repo, lint
):
    (repo / "notes.md").write_text(
        "# Notes\n\nA boot takes a minute.\n\nIt took 34 s on the A51.\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "notes.md:5:21" in result.stdout


def test_when_a_page_names_the_maintainer_lint_fails(repo, lint):
    (repo / "notes.md").write_text("# Notes\n\nAsk Chris.\n")

    result = lint()

    assert result.returncode != 0
    assert "notes.md:3:5" in result.stdout


def test_when_pyproject_names_the_maintainer_as_the_author_lint_passes(
    repo, lint
):
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "spam"\nauthors = [{ name = "Chris Hurley" }]\n'
    )

    assert lint().returncode == 0


def test_when_a_page_names_the_maintainers_github_account_lint_fails(
    repo, lint
):
    (repo / "notes.md").write_text("# Notes\n\nPing cphurley82 about it.\n")

    result = lint()

    assert result.returncode != 0
    assert "notes.md:3:6" in result.stdout


def test_when_a_page_links_to_the_repository_by_its_url_lint_passes(repo, lint):
    (repo / "notes.md").write_text(
        "# Notes\n\nClone <https://github.com/cphurley82/socpuppet>.\n"
    )

    assert lint().returncode == 0


def test_when_a_page_dates_a_measurement_lint_fails_and_names_the_place(
    repo, lint
):
    (repo / "docs").mkdir()
    (repo / "docs" / "notes.md").write_text(
        "# Notes\n\nMeasured on 2026-10-26, on a laptop.\n"
    )

    result = lint()

    assert result.returncode != 0
    assert "docs/notes.md:3:13" in result.stdout


@pytest.mark.parametrize(
    "page", ["docs/history/decisions.md", "docs/upstream.md", "docs/roadmap.md"]
)
def test_when_a_page_that_keeps_the_record_dates_an_entry_lint_passes(
    repo, lint, page
):
    (repo / page).parent.mkdir(parents=True)
    (repo / page).write_text("# Record\n\n- 2026-10-26: it was decided.\n")

    assert lint().returncode == 0


def test_when_a_file_that_is_not_a_page_carries_a_date_lint_passes(repo, lint):
    (repo / "pins.cmake").write_text(
        "GIT_TAG 4d63017c88a147839d49028d0c60666d691460cc # 2026-09-24\n"
    )

    assert lint().returncode == 0


def test_when_a_binary_file_happens_to_hold_a_name_lint_passes(repo, lint):
    (repo / "photo.bin").write_bytes(b"\x89PNG\x00\xff\xfe Chris \x00\x01")

    assert lint().returncode == 0


def test_when_the_lints_own_tests_spell_the_names_they_look_for_lint_passes(
    repo, lint
):
    tests = repo / "tests" / "tooling" / "test_lint_stranger.py"
    tests.parent.mkdir(parents=True)
    tests.write_text('"""The lint."""\n\nNAME = "Chris"\n')

    # The stranger alone: the other linters have their own say on a .py.
    assert lint("stranger").returncode == 0


def test_when_the_licence_names_the_account_that_holds_the_copyright_lint_passes(
    repo, lint
):
    (repo / "LICENSE").write_text(
        "MIT License\n\nCopyright (c) 2026 cphurley82\n"
    )

    assert lint().returncode == 0


def test_when_the_lint_itself_spells_the_names_it_looks_for_lint_passes(
    repo, lint
):
    (repo / "tools").mkdir()
    (repo / "tools" / "stranger.py").write_text(
        '"""The lint."""\n\nNAME = "Chris"\n'
    )

    # The stranger alone: the other linters have their own say on a .py.
    assert lint("stranger").returncode == 0
