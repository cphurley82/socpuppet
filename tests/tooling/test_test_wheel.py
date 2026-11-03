"""tools/test_wheel.py, which installs a wheel and runs the Python tests on it.

The tool is run for real, with a fake for uv on its path, and a fake for a
Python of this machine's, as Homebrew's is, off it. The fakes log what they
were asked, and make a venv whose python is a fake too, which logs what it
was asked and where, so the tests can say how socpuppet was installed and
where its tests ran without installing anything.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "test_wheel.py"
PYTHON = (REPO / ".python-version").read_text().strip()
# The pytest the wheels' tests take, as pyproject.toml tells cibuildwheel and
# the tool alike: under a cap while pytest-xdist's loadgroup needs one
# (docs/upstream.md).
with (REPO / "pyproject.toml").open("rb") as _pyproject:
    TEST_PACKAGES = tomllib.load(_pyproject)["tool"]["cibuildwheel"][
        "test-requires"
    ]
(PYTEST,) = [
    each
    for each in TEST_PACKAGES
    if each.startswith("pytest") and "xdist" not in each
]


def load(path, beside=()):
    """Import a file as a module, with `beside` on the path while it loads."""
    sys.path[:0] = [str(each) for each in beside]
    try:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        del sys.path[: len(beside)]
    return module


# The front door's tests, for the pages they read and how they name a file.
FRONT_DOOR = load(
    REPO / "tests" / "python" / "test_front_door.py",
    beside=(REPO / "tests" / "python",),
)

# uv, a Python of this machine's, and a venv's python. `uv venv DIR` and
# `python3 -m venv DIR` make DIR/bin/python, which is this same script. Each
# logs its name, arguments and directory, and the files under it.
FAKE = r"""
import json, os, shutil, sys
args = sys.argv[1:]
with open(os.environ["LOG"], "a") as log:
    log.write(json.dumps({
        "name": os.path.basename(sys.argv[0]),
        "program": sys.argv[0],
        "args": args,
        "cwd": os.getcwd(),
        "has_tests": os.path.exists("tests/python/conftest.py"),
        "files": sorted(
            os.path.relpath(os.path.join(root, name))
            for root, _, names in os.walk(".")
            for name in names
        ),
    }) + "\n")
if (os.path.basename(sys.argv[0]) == "uv" and args[0] == "venv") or args[
    :2
] == ["-m", "venv"]:
    python = os.path.join(args[-1], "bin", "python")
    os.makedirs(os.path.dirname(python))
    shutil.copy(sys.argv[0], python)
"""


@pytest.fixture
def test_wheel(tmp_path):
    """Run the tool; returns (result, [the programs' calls]).

    run(how, *what, tests=()) installs a wheel with uv or pip, or tests a
    Python's own socpuppet with `installed`; what is installed is the wheel
    or that Python unless named.
    """
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    uv = bin_directory / "uv"
    uv.write_text(f"#!{sys.executable}\n{FAKE}")
    uv.chmod(0o755)
    # A Python of this machine's, off the path, by a link to where it is,
    # as Homebrew's python3.15 is.
    homebrew = tmp_path / "homebrew"
    (homebrew / "Cellar").mkdir(parents=True)
    (homebrew / "bin").mkdir()
    python = homebrew / "Cellar" / "python3.15"
    python.write_text(f"#!{sys.executable}\n{FAKE}")
    python.chmod(0o755)
    (homebrew / "bin" / "python3.15").symlink_to(python)
    wheel = tmp_path / "socpuppet-0.0.1-cp313-cp313-spam.whl"
    wheel.touch()
    log = tmp_path / "log"

    def run(how, *what, tests=()):
        if not what:
            what = (str(run.python if how == "installed" else wheel),)
        result = subprocess.run(
            [sys.executable, str(TOOL), how, *what, *tests],
            env={
                **os.environ,
                "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
                "LOG": str(log),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        lines = log.read_text().splitlines() if log.exists() else []
        return result, [json.loads(line) for line in lines]

    run.wheel = wheel
    run.python = homebrew / "bin" / "python3.15"
    return run


def test_with_uv_the_wheel_and_pytest_are_installed_by_uv_into_a_new_venv(
    test_wheel,
):
    result, calls = test_wheel("uv")

    assert result.returncode == 0, result.stdout
    assert venv_made(calls)
    (install,) = [
        c["args"]
        for c in calls
        if c["name"] == "uv" and c["args"][:2] == ["pip", "install"]
    ]
    assert str(test_wheel.wheel) in install
    assert PYTEST in install


def test_with_pip_the_wheel_and_pytest_are_installed_by_the_venvs_own_pip(
    test_wheel,
):
    result, calls = test_wheel("pip")

    assert result.returncode == 0, result.stdout
    assert "--seed" in venv_made(calls)
    (install,) = [
        c["args"]
        for c in calls
        if c["name"] == "python" and c["args"][:3] == ["-m", "pip", "install"]
    ]
    assert str(test_wheel.wheel) in install
    assert PYTEST in install


@pytest.mark.parametrize("installer", ["uv", "pip"])
def test_the_venv_is_made_with_the_python_the_tools_are_pinned_to(
    test_wheel, installer
):
    _, calls = test_wheel(installer)

    venv = venv_made(calls)
    assert venv[venv.index("--python") + 1] == PYTHON


@pytest.mark.parametrize("installer", ["uv", "pip"])
def test_the_python_tests_run_from_a_copy_outside_the_source_tree(
    test_wheel, installer
):
    _, calls = test_wheel(installer)

    (tests,) = [c for c in calls if c["args"][:2] == ["-m", "pytest"]]
    assert tests["has_tests"]
    assert not Path(tests["cwd"]).is_relative_to(REPO)


@pytest.mark.parametrize("installer", ["uv", "pip"])
def test_the_python_tests_run_on_every_core_long_ones_first(
    test_wheel, installer
):
    _, calls = test_wheel(installer)

    (install,) = [c["args"] for c in calls if "install" in c["args"]]
    assert "pytest-xdist" in install
    (tests,) = [c["args"] for c in calls if c["args"][:2] == ["-m", "pytest"]]
    assert tests[2:] == [
        *("-n", "auto", "--dist", "loadgroup", "--no-loadscope-reorder"),
        "tests/python",
    ]


@pytest.mark.parametrize("installer", ["uv", "pip"])
def test_every_page_the_front_door_reads_is_beside_the_copied_tests(
    test_wheel, installer
):
    # With the examples their excerpts name, so the front door runs its
    # programs on the installed package as it runs them from the checkout.
    named = {
        name
        for page in FRONT_DOOR.PAGES
        for name in FRONT_DOOR.FILE.findall((REPO / page).read_text())
    }

    _, calls = test_wheel(installer)

    (tests,) = [c for c in calls if c["args"][:2] == ["-m", "pytest"]]
    assert set(FRONT_DOOR.PAGES) <= set(tests["files"])
    assert named <= set(tests["files"])


@pytest.mark.parametrize("installer", ["uv", "pip"])
def test_the_tests_get_every_package_cibuildwheel_is_told_they_require(
    test_wheel, installer
):
    # One list, in pyproject.toml, for both ways a wheel is tested.
    with (REPO / "pyproject.toml").open("rb") as pyproject:
        required = tomllib.load(pyproject)["tool"]["cibuildwheel"][
            "test-requires"
        ]

    _, calls = test_wheel(installer)

    (install,) = [c["args"] for c in calls if "install" in c["args"]]
    assert set(required) <= set(install)


@pytest.mark.parametrize("installer", ["uv", "pip"])
def test_a_requirement_in_place_of_a_wheel_is_handed_to_the_installer_as_it_is(
    test_wheel, installer
):
    # As a user installs from PyPI: socpuppet==0.1.0.
    result, calls = test_wheel(installer, "spam==0.1.0")

    assert result.returncode == 0, result.stdout
    (install,) = [c["args"] for c in calls if "install" in c["args"]]
    assert "spam==0.1.0" in install


def test_installed_tests_the_socpuppet_the_python_named_already_has(
    test_wheel,
):
    # As Homebrew installs it: into its Python's own site-packages, which
    # a venv made with --system-site-packages sees.
    result, calls = test_wheel("installed")

    assert result.returncode == 0, result.stdout
    (made,) = [c for c in calls if c["args"][:2] == ["-m", "venv"]]
    assert made["program"] == str(test_wheel.python)
    assert "--system-site-packages" in made["args"]
    (install,) = [c["args"] for c in calls if "install" in c["args"]]
    packages = {
        each
        for each in install[install.index("install") + 1 :]
        if not each.startswith("-")
    }
    assert packages == set(TEST_PACKAGES)


@pytest.mark.parametrize("how", ["uv", "pip", "installed"])
def test_the_tests_named_after_what_is_installed_are_the_only_ones_run(
    test_wheel, how
):
    _, calls = test_wheel(how, tests=["tests/python/test_front_door.py"])

    (tests,) = [c["args"] for c in calls if c["args"][:2] == ["-m", "pytest"]]
    assert "tests/python/test_front_door.py" in tests
    assert "tests/python" not in tests


def test_the_cap_on_pytest_is_the_same_for_wheels_dev_tools_and_dependabot():
    # pytest-xdist's loadgroup groups nothing above the cap
    # (docs/upstream.md), and the wheel's tests take the newest pytest they
    # are allowed.
    with (REPO / "pyproject.toml").open("rb") as pyproject:
        project = tomllib.load(pyproject)
    dependabot = yaml.safe_load((REPO / ".github/dependabot.yml").read_text())

    (for_the_dev_tools,) = [
        each
        for each in project["dependency-groups"]["dev"]
        if isinstance(each, str)
        and each.startswith("pytest")
        and "xdist" not in each
    ]
    (ignored,) = [
        each["versions"]
        for update in dependabot["updates"]
        for each in update.get("ignore", [])
        if each["dependency-name"] == "pytest"
    ]

    assert PYTEST == "pytest<9.2"
    assert for_the_dev_tools == "pytest>=9,<9.2"
    assert ignored == [">=9.2"]


def test_an_unknown_installer_is_refused_with_the_usage(test_wheel):
    result, calls = test_wheel("spam")

    assert result.returncode == 2
    assert "uv" in result.stdout
    assert "pip" in result.stdout
    assert calls == []


def venv_made(calls):
    """The arguments uv made the venv with."""
    (venv,) = [
        c["args"] for c in calls if c["name"] == "uv" and c["args"][0] == "venv"
    ]
    return venv


def test_the_test_cibuildwheel_runs_on_each_wheel_boots_no_firmware():
    # A wheel for each Python on each machine, and a boot of everything on
    # each would be hours. tools/test_wheel.py boots one wheel, installed.
    with (REPO / "pyproject.toml").open("rb") as pyproject:
        cibuildwheel = tomllib.load(pyproject)["tool"]["cibuildwheel"]

    assert "SOCPUPPET_FIRMWARE_DIR" in cibuildwheel["test-environment"]
    # 💡 The test of a wheel with nothing built names no directory, and fetches.
    assert '-m "not long"' in cibuildwheel["test-command"]
