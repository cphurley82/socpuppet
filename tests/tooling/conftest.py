"""Fixtures for the tests of the repo's own tooling."""

import os
import pty
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# The real configuration, so the tests check the rules the repo is held to.
CONFIG_FILES = [
    ".clang-format",
    ".clang-tidy",
    ".coveragerc",
    "CPPLINT.cfg",
    "ruff.toml",
    "mypy.ini",
    ".rumdl.toml",
    # What the C written for Zephyr is held to, where it lives.
    "firmware/.clang-format",
    "firmware/CPPLINT.cfg",
    "python/socpuppet/zephyr_module/.clang-format",
    "python/socpuppet/zephyr_module/CPPLINT.cfg",
]

LINT = REPO / "tools" / "lint.py"


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repository carrying the real lint configuration."""
    _make_repo(tmp_path)
    return tmp_path


def _make_repo(path):
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    for name in CONFIG_FILES:
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / name, path / name)


@pytest.fixture
def git(repo):
    """Run a git command in the throwaway repository."""

    def run(*args):
        subprocess.run(["git", *args], cwd=repo, check=True)

    return run


@pytest.fixture
def lint(repo):
    """Run tools/lint.py in the throwaway repository, output going to a pipe."""

    def run(*args, cwd=repo, stdin="", python=sys.executable):
        return subprocess.run(
            [str(python), str(LINT), *args],
            cwd=cwd,
            # Only the system's own directories: lint must find its tools
            # without the virtual environment being activated.
            env={**os.environ, "PATH": os.defpath},
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    return run


@pytest.fixture
def python_without_the_linters(tmp_path_factory):
    """An interpreter in a virtual environment with nothing installed."""
    bare = tmp_path_factory.mktemp("bare") / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(bare)], check=True
    )
    return bare / "bin" / "python"


@pytest.fixture
def check_wheel():
    """Run tools/check_wheel.py on a wheel."""

    def run(wheel):
        return subprocess.run(
            [
                sys.executable,
                str(REPO / "tools" / "check_wheel.py"),
                str(wheel),
            ],
            capture_output=True,
            text=True,
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
        process = subprocess.Popen(
            [sys.executable, str(LINT)], cwd=repo, stdout=theirs, stderr=theirs
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


class CMakeProject:
    """A small CMake project that uses the repo's cmake/ modules."""

    def __init__(self, source, build):
        self.source = source
        self._build = build

    def configure(self, *options, ci=False):
        """Configure the build tree. Options are given as "NAME=value".

        `ci` says whether to configure as a CI runner does, with CI set in
        the environment. Whether these tests themselves run in CI must not
        decide the outcome. A project that cannot be configured fails the
        test there and then.
        """
        environment = {k: v for k, v in os.environ.items() if k != "CI"}
        if ci:
            environment["CI"] = "true"
        configured = _run(
            _tool("cmake"),
            "-S",
            str(self.source),
            "-B",
            str(self._build),
            "-G",
            "Ninja",
            f"-DCMAKE_MAKE_PROGRAM={_tool('ninja')}",
            # The interpreter that has the developer tools next to it.
            f"-DPython_EXECUTABLE={sys.executable}",
            *(f"-D{option}" for option in options),
            env=environment,
        )
        assert configured.returncode == 0, configured.stdout

    def build(self, target):
        """Build one target."""
        return _run(
            _tool("cmake"), "--build", str(self._build), "--target", target
        )

    def built(self, name):
        """The path of a file the build produced."""
        return self._build / name

    def run(self, program):
        """Run a program the project has built."""
        return _run(str(self._build / program))


@pytest.fixture(scope="module")
def cmake_project(tmp_path_factory):
    """Make a CMake project from its files, given as {path: contents}.

    The project's CMakeLists.txt is written for it, up to and including the
    line that includes cmake/DevChecks.cmake; `cmake_lists` is what follows.
    Its source directory is a throwaway git repository carrying the real
    lint configuration.
    """

    def make(files, cmake_lists):
        root = tmp_path_factory.mktemp("project")
        source = root / "source"
        source.mkdir()
        _make_repo(source)
        for path, contents in files.items():
            (source / path).parent.mkdir(parents=True, exist_ok=True)
            (source / path).write_text(contents)
        (source / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION ${CMAKE_VERSION})\n"
            "project(fixture LANGUAGES CXX)\n"
            f"include({REPO / 'cmake' / 'DevChecks.cmake'})\n" + cmake_lists
        )
        return CMakeProject(source, root / "build")

    return make


def _tool(name):
    """A developer tool installed next to the interpreter, such as cmake."""
    return str(Path(sysconfig.get_path("scripts")) / name)


def _run(*command, env=None):
    return subprocess.run(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
    )
