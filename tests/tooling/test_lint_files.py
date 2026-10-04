"""Which files tools/lint.py looks at."""

CLEAN = "// Clean under any style.\n"
MISFORMATTED = "int   answer( ){return 42;}\n"


def test_when_a_tracked_file_has_been_deleted_from_the_working_tree_lint_passes(
    repo, git, lint
):
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
