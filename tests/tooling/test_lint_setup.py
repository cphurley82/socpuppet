"""tools/lint.py when something it needs is not there."""

import subprocess
import sys


def test_when_the_linters_are_not_installed_lint_says_how_to_install_them(
    repo, tmp_path_factory, lint
):
    (repo / "widget.cpp").write_text("// Clean under any style.\n")
    bare = tmp_path_factory.mktemp("bare") / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(bare)], check=True
    )

    result = lint(python=bare / "bin" / "python")

    assert result.returncode != 0
    assert "uv sync" in result.stdout
    assert "Traceback" not in result.stdout


def test_when_run_outside_a_git_repository_lint_says_so(tmp_path_factory, lint):
    elsewhere = tmp_path_factory.mktemp("elsewhere")

    result = lint(cwd=elsewhere)

    assert result.returncode != 0
    assert f"{elsewhere} is not inside a git repository" in result.stdout
    assert "Traceback" not in result.stdout
