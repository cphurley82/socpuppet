"""tools/qbox.py, which takes a checkout to Linux's prompt on QBox's hart.

The script is run for real, with stand-ins for git, cmake, uv and the rest
on its path (`qbox_stand_ins`), so the tests can say what it asked for
without building QBox or booting Linux.
"""

import importlib.util
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest
from qbox_stand_ins import PROGRAMS, calls, put_in

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "qbox.py"


def load_build_qbox():
    """tools/build_qbox.py as a module, for its lists of what QBox needs."""
    spec = importlib.util.spec_from_file_location(
        "build_qbox", REPO / "tools" / "build_qbox.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "tools"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(REPO / "tools"))
    return module


BUILD_QBOX = load_build_qbox()
#: The commit QBox is pinned to.
PIN = BUILD_QBOX.QBOX_COMMIT
#: pixman, a library QEMU is built against, as apt and Homebrew name it.
_, PIXMAN_APT, PIXMAN_BREW = next(
    each for each in BUILD_QBOX.LIBRARIES if each[0] == "pixman-1"
)


@pytest.fixture
def qbox(tmp_path):
    """Run the script with the stand-ins; returns (result, lines logged).

    The stand-ins are the only programs on its path beside the system's
    own, with a compiler, dtc and uv among them.
    """
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = tmp_path / "log"
    put_in(bin_directory, log, {**PROGRAMS, "c++": "", "dtc": "", "uv": ""})

    def run(*args, missing=""):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(tmp_path / "qbox"),
                *args,
            ],
            env={
                **os.environ,
                "PATH": f"{bin_directory}{os.pathsep}{os.defpath}",
                "MISSING": missing,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        lines = log.read_text().splitlines() if log.exists() else []
        return result, lines

    return run


def test_a_missing_package_stops_it_before_anything_is_built_naming_the_fix(
    qbox,
):
    result, lines = qbox(missing="pixman-1")

    assert result.returncode != 0
    fix = {"Linux": PIXMAN_APT, "Darwin": f"brew install {PIXMAN_BREW}"}
    assert fix[platform.system()] in result.stdout
    assert not calls(lines, "git")
    assert not calls(lines, "cmake")


def test_with_no_qbox_built_it_builds_qbox_at_its_pin_into_the_root(
    qbox, tmp_path
):
    result, lines = qbox()

    assert result.returncode == 0, result.stdout
    assert calls(lines, "git", "checkout", PIN)
    install = tmp_path / "qbox" / "install"
    assert calls(lines, "cmake", f"-DCMAKE_INSTALL_PREFIX={install}")
    assert calls(lines, "cmake", "--install")


def test_with_qbox_built_it_builds_qbox_no_more_and_says_how_to(qbox):
    qbox()

    result, lines = qbox()

    assert result.returncode == 0, result.stdout
    assert len(calls(lines, "git", "clone")) == 1
    assert len(calls(lines, "cmake", "--install")) == 1
    assert "delete" in result.stdout.lower()


def test_then_it_builds_socpuppet_against_that_qbox_with_the_qbox_preset(
    qbox, tmp_path
):
    result, lines = qbox()

    assert result.returncode == 0, result.stdout
    install = tmp_path / "qbox" / "install"
    assert calls(
        lines, "cmake", "--preset", "qbox", f"-DSOCPUPPET_QBOX_DIR={install}"
    )
    assert calls(lines, "cmake", "--build", "--preset", "qbox")


def test_the_jobs_option_is_how_many_files_each_build_compiles_at_once(qbox):
    result, lines = qbox("--jobs", "3")

    assert result.returncode == 0, result.stdout
    assert calls(lines, "cmake", "--build", "--parallel", "3")
    assert calls(
        lines, "cmake", "--build", "--preset", "qbox", "--parallel", "3"
    )
