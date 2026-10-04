"""Fixtures for the tests of the repo's own tooling."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# The real configuration, so the tests check the rules the repo is held to.
CONFIG_FILES = [".clang-format"]


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repository carrying the real lint configuration."""
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    for name in CONFIG_FILES:
        shutil.copy(REPO / name, tmp_path / name)
    return tmp_path


@pytest.fixture
def lint(repo):
    """Run tools/lint.py in the throwaway repository."""

    def run(*args):
        return subprocess.run(
            [sys.executable, str(REPO / "tools" / "lint.py"), *args],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    return run
