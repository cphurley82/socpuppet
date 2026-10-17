#!/usr/bin/env python3
"""Install a built wheel in a clean venv, and run the Python tests on it.

Usage: tools/test_wheel.py uv|pip WHEEL

The tests run from a copy outside the source tree, so that what they
import is the installed package and not the one in python/.
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
ON_EVERY_CORE = ("-n", "auto", "--dist", "loadscope", "--no-loadscope-reorder")


def main() -> int:
    """Install the wheel and test it. Returns the tests' exit status."""
    parser = argparse.ArgumentParser(
        prog="tools/test_wheel.py", description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "installer",
        choices=("uv", "pip"),
        help="what installs the wheel, as a user would: uv or pip",
    )
    parser.add_argument("wheel", type=Path, help="the wheel to install")
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    # A wheel is built for one Python version; it is installed under that
    # same one.
    python = (REPOSITORY / ".python-version").read_text().strip()
    with tempfile.TemporaryDirectory() as scratch:
        shutil.copytree(REPOSITORY / "tests" / "python", Path(scratch, "tests"))
        venv = Path(scratch, "venv")
        interpreter = str(venv / "bin" / "python")
        if args.installer == "uv":
            run(scratch, "uv", "venv", "--quiet", "--python", python, str(venv))
            run(
                scratch,
                *("uv", "pip", "install", "--quiet", "--python", interpreter),
                *(str(wheel), *TEST_PACKAGES),
            )
        else:
            run(
                scratch,
                *("uv", "venv", "--quiet", "--python", python, "--seed"),
                str(venv),
            )
            run(
                scratch,
                *(interpreter, "-m", "pip", "install", "--quiet"),
                *(str(wheel), *TEST_PACKAGES),
            )
        return subprocess.run(
            [interpreter, "-m", "pytest", *ON_EVERY_CORE, "tests"],
            cwd=scratch,
        ).returncode


def run(directory: str, *command: str) -> None:
    """Run a step of the install, and stop if it fails."""
    if subprocess.run(command, cwd=directory).returncode != 0:
        sys.exit(f"test_wheel.py: {' '.join(command)} failed")


if __name__ == "__main__":
    sys.exit(main())
