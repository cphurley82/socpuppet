"""Which files tools/lint.py looks at."""

CLEAN = "// Clean under any style.\n"
MISFORMATTED = "int   answer( ){return 42;}\n"


def test_when_a_tracked_file_has_been_deleted_from_the_working_tree_lint_passes(
    repo, git, lint
):
    # A second file stays, so that there is still C++ for the linter to run on.
    (repo / "kept.cpp").write_text(CLEAN)
    (repo / "gone.cpp").write_text(CLEAN)
    git("add", "kept.cpp", "gone.cpp")
    (repo / "gone.cpp").unlink()

    assert lint().returncode == 0


def test_when_run_from_a_subdirectory_a_problem_elsewhere_in_the_repository_fails(
    repo, lint
):
    (repo / "widget.cpp").write_text(MISFORMATTED)
    (repo / "docs").mkdir()

    assert lint(cwd=repo / "docs").returncode != 0


def test_when_there_are_no_cpp_files_misformatted_code_on_standard_input_does_not_fail_lint(
    repo, lint
):
    (repo / "notes.txt").write_text("Nothing here for any linter.\n")

    assert lint(stdin=MISFORMATTED).returncode == 0


def test_when_a_misformatted_file_is_ignored_by_git_lint_passes(repo, lint):
    (repo / ".gitignore").write_text("build/\n")
    (repo / "build").mkdir()
    (repo / "build" / "generated.cpp").write_text(MISFORMATTED)

    assert lint().returncode == 0


def test_when_a_tracked_file_is_misformatted_lint_fails(repo, git, lint):
    (repo / "widget.cpp").write_text(MISFORMATTED)
    git("add", "widget.cpp")

    assert lint().returncode != 0


def test_when_a_file_with_a_non_ascii_name_is_misformatted_lint_fails(
    repo, lint
):
    (repo / "wídget.cpp").write_text(MISFORMATTED)

    assert lint().returncode != 0
