#!/usr/bin/env python3
"""Test socpuppet as a user gets it: installed into a venv, or a Python's.

Usage: tools/test_wheel.py uv|pip WHEEL|REQUIREMENT [TEST ...]
       tools/test_wheel.py installed PYTHON [TEST ...]

uv or pip installs a built wheel, or a requirement such as
socpuppet==0.1.0 from PyPI, as a user would. `installed` tests the socpuppet
a Python already has, as Homebrew's formula installs it, from a venv that
sees that Python's packages. Each runs the tests named, or all of them.

The tests run from a copy outside the source tree, so that what they
import is the installed package and not the one in python/. The pages a
stranger reads first go beside them, with the examples they name, so the
front door (tests/python/test_front_door.py) runs its programs on the
installed package too, each fetching its image as a user's would.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]

# What the tests need besides the wheel, which pyproject.toml lists once
# for cibuildwheel and for this; and how they are run: on every core, as
# ctest runs them (tests/python/CMakeLists.txt says why).
with (REPOSITORY / "pyproject.toml").open("rb") as _pyproject:
    TEST_PACKAGES = tuple(
        tomllib.load(_pyproject)["tool"]["cibuildwheel"]["test-requires"]
    )
ON_EVERY_CORE = ("-n", "auto", "--dist", "loadgroup", "--no-loadscope-reorder")
#: The Python tests, laid out as in the checkout so that the front door finds
#: its pages two directories up (tests/python/test_front_door.py).
TESTS = "tests/python"
#: What the front door reads, laid out as in the checkout: its pages, and
#: the examples whose excerpts they show.
FRONT_DOOR = ("README.md", "docs/first-show.md", "examples")


def main() -> int:
    """Install socpuppet and test it. Returns the tests' exit status."""
    parser = argparse.ArgumentParser(
        prog="tools/test_wheel.py", description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "how",
        choices=("uv", "pip", "installed"),
        help="how socpuppet is had: installed by uv or pip, as a user "
        "would, or installed already in a Python",
    )
    parser.add_argument(
        "what",
        help="a wheel, or a requirement such as socpuppet==0.1.0; for "
        "installed, the Python that has it",
    )
    parser.add_argument(
        "tests",
        nargs="*",
        default=[TESTS],
        help="the tests to run, as named in the checkout (under "
        "tests/python); all of them if none",
    )
    args = parser.parse_args()
    # A file, a wheel or a Python, is named by its whole path from here, the
    # commands below running elsewhere; a requirement is handed on as it is.
    # Not resolved: Homebrew's Python is a link, and is used by its name.
    given = Path(args.what)
    what = str(given.absolute()) if given.is_file() else args.what
    # uv and pip make the venv with the Python the tools are pinned to: a
    # wheel is built for one version, and a requirement fetches that
    # version's wheel.
    python = (REPOSITORY / ".python-version").read_text().strip()
    with tempfile.TemporaryDirectory() as scratch:
        copy_as_checked_in(Path(scratch))
        venv = Path(scratch, "venv")
        interpreter = str(venv / "bin" / "python")
        if args.how == "uv":
            run(scratch, "uv", "venv", "--quiet", "--python", python, str(venv))
            run(
                scratch,
                *("uv", "pip", "install", "--quiet", "--python", interpreter),
                *(what, *TEST_PACKAGES),
            )
        elif args.how == "pip":
            run(
                scratch,
                *("uv", "venv", "--quiet", "--python", python, "--seed"),
                str(venv),
            )
            run(
                scratch,
                *(interpreter, "-m", "pip", "install", "--quiet"),
                *(what, *TEST_PACKAGES),
            )
        else:
            run(
                scratch, what, "-m", "venv", "--system-site-packages", str(venv)
            )
            run(
                scratch,
                *(interpreter, "-m", "pip", "install", "--quiet"),
                *TEST_PACKAGES,
            )
        return subprocess.run(
            [interpreter, "-m", "pytest", *ON_EVERY_CORE, *args.tests],
            cwd=scratch,
        ).returncode


def copy_as_checked_in(scratch: Path) -> None:
    """Lay the tests and the front door out in `scratch` as checked in."""
    for each in (TESTS, *FRONT_DOOR):
        source = REPOSITORY / each
        target = scratch / each
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy(source, target)


def run(directory: str, *command: str) -> None:
    """Run a step of the install, and stop if it fails."""
    if subprocess.run(command, cwd=directory).returncode != 0:
        sys.exit(f"test_wheel.py: {' '.join(command)} failed")


if __name__ == "__main__":
    sys.exit(main())
