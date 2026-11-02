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


#: How the stand-in for the boot of Linux ends.
THE_BOOTS = 7
#: A uv that says what it was handed, the path to socpuppet's package and
#: what came in on its standard input, and ends as a boot of Linux might.
UV = f"""
import os
print("socpuppet from " + os.environ.get("PYTHONPATH", ""))
print("typed: " + sys.stdin.read())
sys.exit({THE_BOOTS})
"""


@pytest.fixture
def qbox(tmp_path):
    """Run the script with the stand-ins; returns (result, lines logged).

    The stand-ins are the only programs on its path beside the system's
    own, with a compiler, dtc and uv among them.
    """
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = tmp_path / "log"
    put_in(bin_directory, log, {**PROGRAMS, "c++": "", "dtc": "", "uv": UV})

    def run(*args, missing="", typed="", configure=""):
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
                "CONFIGURE": configure,
                "QBOX_PACKAGE": str(BUILD_QBOX.PACKAGE),
            },
            input=typed,
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
    assert "❌ QBox's packages" in result.stdout
    fix = {"Linux": PIXMAN_APT, "Darwin": f"brew install {PIXMAN_BREW}"}
    assert fix[platform.system()] in result.stdout
    assert not calls(lines, "git")
    assert not calls(lines, "cmake")


def test_with_no_qbox_built_it_builds_qbox_at_its_pin_into_the_root(
    qbox, tmp_path
):
    result, lines = qbox()

    assert result.returncode == THE_BOOTS, result.stdout
    assert calls(lines, "git", "checkout", PIN)
    assert (tmp_path / "qbox" / "install" / BUILD_QBOX.PACKAGE).is_file()


def test_with_qbox_built_it_builds_qbox_no_more_and_says_how_to_bring_it_up_to_date(
    qbox, tmp_path
):
    qbox()

    result, lines = qbox()

    assert result.returncode == THE_BOOTS, result.stdout
    assert len(calls(lines, "cmake", "--install")) == 1
    assert f"tools/build_qbox.py --root {tmp_path / 'qbox'}" in result.stdout


def test_once_qbox_is_built_it_builds_socpuppet_against_it_with_the_qbox_preset(
    qbox, tmp_path
):
    result, lines = qbox()

    assert result.returncode == THE_BOOTS, result.stdout
    install = tmp_path / "qbox" / "install"
    assert calls(
        lines, "cmake", "--preset", "qbox", f"-DSOCPUPPET_QBOX_DIR={install}"
    )
    assert calls(lines, "cmake", "--build", "--preset", "qbox")


def test_the_jobs_option_is_how_many_files_each_build_compiles_at_once(qbox):
    result, lines = qbox("--jobs", "3")

    assert result.returncode == THE_BOOTS, result.stdout
    assert len(calls(lines, "cmake", "--build", "--parallel", "3")) == 2


def test_it_ends_by_handing_this_terminal_to_linux_on_qboxs_hart(qbox):
    result, lines = qbox(typed="uname -a\n")

    (boot,) = calls(lines, "uv")
    assert boot.split()[1:] == [
        *("run", "python", "-m", "socpuppet"),
        *("linux", "--cpu", "qbox_cpu"),
    ]
    assert f"socpuppet from {REPO / 'python'}" in result.stdout
    assert "typed: uname -a" in result.stdout
    assert result.returncode == THE_BOOTS


def test_a_step_that_fails_ends_it_in_a_line_that_says_which_and_boots_nothing(
    qbox,
):
    result, lines = qbox(configure="fails")

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1].startswith("tools/qbox.py: cmake ")
    assert not calls(lines, "uv")


def test_linux_is_given_the_checkouts_package_ahead_of_whatever_pythonpath_had(
    qbox, monkeypatch
):
    monkeypatch.setenv("PYTHONPATH", "/spam/eggs")

    result, _ = qbox()

    assert f"socpuppet from {REPO / 'python'}{os.pathsep}/spam/eggs" in (
        result.stdout
    )
