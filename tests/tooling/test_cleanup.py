"""tools/cleanup.py: what is in build/, who made it, and clearing it away.

Each test runs the tool as a person would, on a throwaway repository with
build trees of a few megabytes, and reads what it says and what it left.
"""

import importlib.util
import json
import os
import pty
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLEANUP = REPO / "tools" / "cleanup.py"
MEGABYTE = 1024 * 1024


def load(name):
    """A script of tools/, as a module."""
    spec = importlib.util.spec_from_file_location(
        name, REPO / "tools" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cleanup(repo):
    """Run tools/cleanup.py over the throwaway repository."""

    def run(*args, no_color=True):
        env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
        if no_color:
            env["NO_COLOR"] = "1"
        return subprocess.run(
            [sys.executable, str(CLEANUP), "--root", str(repo), *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    return run


@pytest.fixture
def cleanup_on_a_terminal(repo, monkeypatch):
    """Run tools/cleanup.py with its output going to a terminal.

    Returns what the terminal was sent.
    """
    # The developer's own preference must not decide the outcome.
    monkeypatch.delenv("NO_COLOR", raising=False)

    def run():
        ours, theirs = pty.openpty()
        process = subprocess.Popen(
            [sys.executable, str(CLEANUP), "--root", str(repo)],
            stdout=theirs,
            stderr=theirs,
        )
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


def fill(repo, path, megabytes):
    """Write a file of `megabytes` at `path`, under the repository."""
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(os.urandom(int(megabytes * MEGABYTE)))
    return file


def line_of(output, path):
    """The columns of the line of the report that names `path`."""
    (line,) = [each for each in output.splitlines() if f" {path} " in each]
    return re.split(r"\s{2,}", line.strip())


def test_the_report_lists_each_owned_tree_as_current_with_its_size_who_makes_it_how_long_that_takes_and_the_level_that_removes_it(
    repo, cleanup
):
    fill(repo, "build/dev/spam.o", 3)
    fill(repo, "build/qbox/install/eggs.so", 2)

    ran = cleanup()

    assert ran.returncode == 0, ran.stdout
    assert line_of(ran.stdout, "build/dev") == [
        "current",
        "build/dev",
        "3.0 MB",
        "the presets (CMakePresets.json)",
        "minutes",
        "trees",
    ]
    assert line_of(ran.stdout, "build/qbox") == [
        "current",
        "build/qbox",
        "2.0 MB",
        "tools/build_qbox.py",
        "about an hour",
        "everything",
    ]


def test_the_table_of_owned_trees_covers_every_tree_a_tool_of_today_builds_in():
    owned = [tree.path for tree in load("cleanup").TREES]

    assert {
        path
        for path in trees_the_tools_build_in()
        if not any(owned_by(path, tree) for tree in owned)
    } == set()


def trees_the_tools_build_in():
    """Every path under build/ that ci.py, the presets or pyproject names."""
    runner = load("ci")
    presets = json.loads((REPO / "CMakePresets.json").read_text())
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    return {
        *(
            used
            for job in runner.JOBS
            for used in job.uses_now()
            if used.startswith("build/")
        ),
        str(runner.LOGS.relative_to(runner.REPO)),
        runner.WHEELHOUSE,
        runner.SDIST,
        runner.CCACHE,
        *(
            preset["binaryDir"].removeprefix("${sourceDir}/")
            for preset in presets["configurePresets"]
            if "binaryDir" in preset
        ),
        pyproject["tool"]["scikit-build"]["build-dir"],
    }


def owned_by(path, tree):
    """Whether `path` is the owned `tree` or under it."""
    return path == tree or path.startswith(f"{tree}/")


def test_with_nothing_in_build_the_report_says_there_is_nothing_to_clean(
    cleanup,
):
    ran = cleanup()

    assert ran.returncode == 0, ran.stdout
    assert "Nothing to clean" in ran.stdout


def test_on_a_terminal_the_report_colors_current_green(
    repo, cleanup_on_a_terminal
):
    fill(repo, "build/dev/spam.o", 1)

    assert "\x1b[32mcurrent" in cleanup_on_a_terminal()


def test_the_report_is_plain_when_stdout_is_not_a_terminal(repo, cleanup):
    fill(repo, "build/dev/spam.o", 1)

    ran = cleanup(no_color=False)

    assert "current" in ran.stdout
    assert "\x1b" not in ran.stdout
