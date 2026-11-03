"""pyproject.toml, held to itself where it says one thing twice."""

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
with (REPO / "pyproject.toml").open("rb") as _pyproject:
    PYPROJECT = tomllib.load(_pyproject)

#: A CPython wheel cibuildwheel builds, as its `build` selector names it.
BUILT = re.compile(r"cp3(\d+)-")
#: A version of Python the project says it supports, as PyPI lists it.
CLASSIFIED = re.compile(r"Programming Language :: Python :: 3\.(\d+)")


def test_each_python_a_wheel_is_built_for_is_a_classifier_and_no_other():
    classified = {
        match.group(1)
        for each in PYPROJECT["project"]["classifiers"]
        if (match := CLASSIFIED.fullmatch(each))
    }

    assert built_pythons() == classified


def test_a_wheel_is_built_for_python_3_15():
    # 💡 3.15 is the python3 Homebrew installs, and the tap installs into it.
    assert "15" in built_pythons()


def built_pythons():
    """The minor versions of Python 3 that cibuildwheel builds wheels for."""
    found = set()
    for selector in PYPROJECT["tool"]["cibuildwheel"]["build"]:
        match = BUILT.match(selector)
        assert match, f"{selector} names no CPython 3 wheel"
        found.add(match.group(1))
    return found
