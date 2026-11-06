"""tools/cleanup.py: what is in build/, who made it, and clearing it away.

Each test runs the tool as a person would, on a throwaway repository with
build trees of a few megabytes, and reads what it says and what it left.
"""

import importlib.util
import json
import os
import pty
import re
import shutil
import subprocess
import sys
import sysconfig
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
    """Run tools/cleanup.py over the throwaway repository.

    The repository ignores what the real one does.
    """
    shutil.copy(REPO / ".gitignore", repo / ".gitignore")

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


def test_what_is_under_build_that_no_tool_of_today_makes_is_unused_with_its_size(
    repo, cleanup
):
    fill(repo, "build/speed-x/spam.o", 2)
    fill(repo, "build/asmjit/eggs.a", 1)
    fill(repo, "build/spam.log", 0.5)

    ran = cleanup()

    assert ran.returncode == 0, ran.stdout
    for path, size in (
        ("build/speed-x", "2.0 MB"),
        ("build/asmjit", "1.0 MB"),
        ("build/spam.log", "512.0 KB"),
    ):
        assert line_of(ran.stdout, path) == [
            "unused",
            path,
            size,
            "no tool of today",
            "nothing",
            "unused",
        ]


def test_an_ignored_leftover_outside_build_is_unused(repo, cleanup):
    for leftover in ("cable.pcap", ".coverage", "dist/spam.whl"):
        fill(repo, leftover, 1)
    fill(repo, "python/spam.egg-info/PKG-INFO", 1)

    ran = cleanup()

    for path in ("cable.pcap", ".coverage", "dist", "python/spam.egg-info"):
        assert line_of(ran.stdout, path) == [
            "unused",
            path,
            "1.0 MB",
            "a leftover outside build/",
            "nothing",
            "unused",
        ]


def test_what_git_ignores_that_is_no_leftover_is_not_reported(repo, cleanup):
    fill(repo, ".venv/lib/spam.py", 1)
    fill(repo, "tools/__pycache__/spam.pyc", 1)

    ran = cleanup()

    assert ".venv" not in ran.stdout
    assert "__pycache__" not in ran.stdout


def test_a_leftover_by_its_name_that_git_does_not_ignore_is_not_reported(
    repo, cleanup
):
    with (repo / ".gitignore").open("a") as gitignore:
        gitignore.write("!spam.pcap\n")
    fill(repo, "spam.pcap", 1)

    ran = cleanup()

    assert "spam.pcap" not in ran.stdout


def test_an_extension_built_for_another_platform_is_unused_and_this_platforms_is_current(
    repo, cleanup
):
    this = f"python/socpuppet/_core{sysconfig.get_config_var('EXT_SUFFIX')}"
    other = "python/socpuppet/_core.cpython-312-spam-eggs.so"
    fill(repo, this, 1)
    fill(repo, other, 1)

    ran = cleanup()

    assert line_of(ran.stdout, this) == [
        "current",
        this,
        "1.0 MB",
        "the presets (CMakePresets.json)",
        "minutes",
        "trees",
    ]
    assert line_of(ran.stdout, other) == [
        "unused",
        other,
        "1.0 MB",
        "a build for another platform",
        "nothing",
        "unused",
    ]


def test_the_report_totals_what_each_level_would_free_each_with_the_levels_before_it(
    repo, cleanup
):
    fill(repo, "build/speed-x/spam.o", 1)
    fill(repo, "build/dev/spam.o", 2)
    fill(repo, "build/qbox/spam.o", 3)

    ran = cleanup()

    assert (
        "Each level would free: unused 1.0 MB; trees 3.0 MB; everything 6.0 MB."
        in ran.stdout
    )


def test_a_counter_left_under_a_preset_tree_is_stale_and_repair_deletes_only_it(
    repo, cleanup
):
    counter = fill(repo, "build/dev/a/b.gcda", 0.25)
    beside = fill(repo, "build/dev/a/b.o", 1)

    reported = cleanup()
    repaired = cleanup("repair")

    assert line_of(reported.stdout, "build/dev/**/*.gcda") == [
        "stale",
        "build/dev/**/*.gcda",
        "256.0 KB",
        "1 counter of an interrupted coverage run",
        "nothing",
        "repair",
    ]
    assert "🧹 deleted 1 *.gcda under build/dev" in repaired.stdout
    assert not counter.exists()
    assert beside.exists()


def test_a_counter_in_a_tree_the_presets_do_not_make_is_not_stale_and_repair_keeps_it(
    repo, cleanup
):
    counter = fill(repo, "build/qbox/build/spam.gcda", 0.25)

    reported = cleanup()
    cleanup("repair")

    assert "build/qbox/**/*.gcda" not in reported.stdout
    assert counter.exists()


def test_repair_removes_nothing_unused_and_no_tree(repo, cleanup):
    unused = fill(repo, "build/speed-x/spam.o", 1)
    tree = fill(repo, "build/dev/spam.o", 1)
    leftover = fill(repo, "cable.pcap", 1)

    ran = cleanup("repair")

    assert ran.returncode == 0, ran.stdout
    assert unused.exists()
    assert tree.exists()
    assert leftover.exists()
