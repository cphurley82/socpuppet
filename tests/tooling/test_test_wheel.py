"""tools/test_wheel.py, which installs a wheel and runs the Python tests on it.

The tool is run for real, with a stand-in for uv on its path. The stand-in
logs what it was asked, and makes a venv whose python is a stand-in too,
which logs what it was asked and where, so the tests can say how the wheel
was installed and where its tests ran without installing anything.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "test_wheel.py"
PYTHON = (REPO / ".python-version").read_text().strip()

# uv and a venv's python. `uv venv DIR` makes DIR/bin/python, which is this
# same script. Each logs its name, arguments and directory, and whether
# the directory has the Python tests in it.
STAND_IN = r"""
import json, os, shutil, sys
args = sys.argv[1:]
with open(os.environ["LOG"], "a") as log:
    log.write(json.dumps({
        "name": os.path.basename(sys.argv[0]),
        "args": args,
        "cwd": os.getcwd(),
        "has_tests": os.path.exists("tests/conftest.py"),
    }) + "\n")
if os.path.basename(sys.argv[0]) == "uv" and args[0] == "venv":
    python = os.path.join(args[-1], "bin", "python")
    os.makedirs(os.path.dirname(python))
    shutil.copy(sys.argv[0], python)
"""


@pytest.fixture
def test_wheel(tmp_path):
    """Run the tool on a wheel; returns (result, [the programs' calls])."""
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    uv = bin_directory / "uv"
    uv.write_text(f"#!{sys.executable}\n{STAND_IN}")
    uv.chmod(0o755)
    wheel = tmp_path / "socpuppet-0.0.1-cp313-cp313-spam.whl"
    wheel.touch()
    log = tmp_path / "log"

    def run(installer):
        result = subprocess.run(
            [sys.executable, str(TOOL), installer, str(wheel)],
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
    assert "pytest" in install


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
    assert "pytest" in install


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
def test_the_python_tests_run_on_every_core_as_ctest_runs_them(
    test_wheel, installer
):
    _, calls = test_wheel(installer)

    (install,) = [c["args"] for c in calls if "install" in c["args"]]
    assert "pytest-xdist" in install
    (tests,) = [c["args"] for c in calls if c["args"][:2] == ["-m", "pytest"]]
    assert tests[2:] == [
        *("-n", "auto", "--dist", "loadscope", "--no-loadscope-reorder"),
        "tests",
    ]


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
