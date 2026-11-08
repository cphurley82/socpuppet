"""pyproject.toml, held to itself where it says one thing twice."""

import importlib
import importlib.metadata
import re
import sys
import sysconfig
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
LINT = importlib.import_module("lint")
TIDY = importlib.import_module("tidy")
with (REPO / "pyproject.toml").open("rb") as _pyproject:
    PYPROJECT = tomllib.load(_pyproject)

#: The name a requirement in a dependency group is for.
REQUIREMENT_NAME = re.compile(r"[A-Za-z0-9._-]+")
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


def test_what_a_linux_wheel_runs_first_is_in_the_source_distribution():
    # tools/ci.py builds this machine's wheel from an sdist, which
    # cibuildwheel unpacks as {package}, so the script before-all names has
    # to be in it: in the repo, and under no directory the sdist leaves out.
    before_all = PYPROJECT["tool"]["cibuildwheel"]["linux"]["before-all"]
    script = Path(before_all.split("{package}/")[1].split()[0])
    left_out = PYPROJECT["tool"]["scikit-build"]["sdist"]["exclude"]

    assert (REPO / script).is_file()
    assert script.parts[0] not in left_out


def test_the_linters_programs_come_from_the_lint_group_alone():
    # 💡 So that a job that never lints can go without them: two are builds
    # that fetch a binary from GitHub at install time (docs/upstream.md).
    groups = PYPROJECT["dependency-groups"]
    from_lint = programs_installed_by(groups["lint"])
    from_dev = programs_installed_by(groups["dev"])

    for program in linters_programs():
        assert program in from_lint, program
        assert program not in from_dev, program


def test_uv_sync_installs_the_linters_with_the_rest_of_the_tools():
    # docs/style.md: `uv sync` installs every tool, with nothing else to run.
    assert {"dev", "lint"} <= set(PYPROJECT["tool"]["uv"]["default-groups"])


def built_pythons():
    """The minor versions of Python 3 that cibuildwheel builds wheels for."""
    found = set()
    for selector in PYPROJECT["tool"]["cibuildwheel"]["build"]:
        match = BUILT.match(selector)
        assert match, f"{selector} names no CPython 3 wheel"
        found.add(match.group(1))
    return found


def linters_programs():
    """The programs tools/lint.py and tools/tidy.py run from the scripts
    directory: every linter's but those that are Python scripts of ours."""
    programs = {linter.check[0] for linter in LINT.LINTERS}
    return (programs - {"python"}) | {TIDY.RUN_CLANG_TIDY, TIDY.CLANG_TIDY}


def programs_installed_by(requirements):
    """The programs the packages a group requires put in the scripts
    directory, read from what `uv sync` installed next to this interpreter."""
    scripts = Path(sysconfig.get_path("scripts")).name
    programs = set()
    for requirement in requirements:
        name = REQUIREMENT_NAME.match(requirement).group()
        try:
            files = importlib.metadata.distribution(name).files or []
        except importlib.metadata.PackageNotFoundError:
            pytest.fail(f"{name} is not installed here: run `uv sync`")
        programs |= {f.name for f in files if scripts in f.parts}
    return programs
