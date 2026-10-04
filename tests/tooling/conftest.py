"""Fixtures for the tests of the repo's own tooling."""

import os
import pty
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# The real configuration, so the tests check the rules the repo is held to.
CONFIG_FILES = [".clang-format", "CPPLINT.cfg", "ruff.toml", "mypy.ini"]

LINT = [sys.executable, str(REPO / "tools" / "lint.py")]


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repository carrying the real lint configuration."""
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    for name in CONFIG_FILES:
        shutil.copy(REPO / name, tmp_path / name)
    return tmp_path


@pytest.fixture
def git(repo):
    """Run a git command in the throwaway repository."""

    def run(*args):
        subprocess.run(["git", *args], cwd=repo, check=True)

    return run


@pytest.fixture
def lint(repo):
    """Run tools/lint.py in the throwaway repository, output going to a pipe."""

    def run(*args, cwd=repo, stdin=""):
        return subprocess.run(
            [*LINT, *args],
            cwd=cwd,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    return run


@pytest.fixture
def check_wheel():
    """Run tools/check_wheel.py on a wheel."""

    def run(wheel):
        return subprocess.run(
            [sys.executable, str(REPO / "tools" / "check_wheel.py"), str(wheel)]
        )

    return run


@pytest.fixture
def lint_on_a_terminal(repo, monkeypatch):
    """Run tools/lint.py in the throwaway repository, output going to a terminal.

    Returns what the terminal was sent.
    """
    # The developer's own preference must not decide the outcome.
    monkeypatch.delenv("NO_COLOR", raising=False)

    def run():
        ours, theirs = pty.openpty()
        process = subprocess.Popen(LINT, cwd=repo, stdout=theirs, stderr=theirs)
        os.close(theirs)
        sent = b""
        while True:
            try:
                chunk = os.read(ours, 4096)
            except OSError:  # Linux reports the far end closing as an error.
                break
            if not chunk:
                break
            sent += chunk
        os.close(ours)
        process.wait()
        return sent.decode("utf-8")

    return run
