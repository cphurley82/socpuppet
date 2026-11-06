"""tools/build_qbox.py, which builds QBox for the qbox_cpu.

The script is run for real, with stand-ins for git, cmake and the rest on
its path (`qbox_stand_ins`).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from qbox_stand_ins import PROGRAMS, calls, put_in

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "build_qbox.py"
# The commit QBox is pinned to, as the tool says.
PIN = next(
    line.split('"')[1]
    for line in SCRIPT.read_text().splitlines()
    if line.startswith("QBOX_COMMIT = ")
)
QBOX_PATCHES = sorted(p.name for p in (REPO / "cmake/patches").glob("qbox-*"))
QEMU_PATCHES = sorted(
    p.name for p in (REPO / "cmake/patches").glob("libqemu-*")
)


@pytest.fixture
def build_qbox(tmp_path):
    """Run the script with the stand-ins; returns (result, lines logged)."""
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = tmp_path / "log"
    put_in(bin_directory, log, PROGRAMS)

    def run(*args, missing="", configure="", broken=""):
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
                "BROKEN": broken,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        lines = log.read_text().splitlines() if log.exists() else []
        return result, lines

    return run


def test_a_first_run_checks_qbox_out_at_the_pin_and_applies_each_patch_once(
    build_qbox,
):
    result, lines = build_qbox()

    assert result.returncode == 0, result.stdout
    assert calls(lines, "git", "clone")
    assert calls(lines, "git", "checkout", PIN)
    for patch in QBOX_PATCHES:
        applied = [
            line
            for line in calls(lines, "git", "apply")
            if line.endswith(patch) and "--check" not in line
        ]
        assert len(applied) == 1, patch


def test_qbox_is_configured_for_riscv64_as_cpp20_without_virgl_and_installed_under_the_root(
    build_qbox, tmp_path
):
    result, lines = build_qbox()

    assert result.returncode == 0, result.stdout
    (configure,) = calls(lines, "cmake", "-S")
    for option in (
        "-DLIBQEMU_TARGETS=riscv64",
        "-DCMAKE_CXX_STANDARD=20",
        "-DGS_ENABLE_VIRGLRENDERER=OFF",
        "-DGS_ENABLE_VIRCLRENDERER=OFF",
        f"-DCMAKE_INSTALL_PREFIX={tmp_path / 'qbox' / 'install'}",
    ):
        assert option in configure.split(), option
    assert calls(lines, "cmake", "--build")
    assert calls(lines, "cmake", "--install")
    assert str(tmp_path / "qbox" / "install") in result.stdout


def test_each_qemu_patch_is_applied_once_to_the_qemu_that_qbox_fetched(
    build_qbox, tmp_path
):
    result, lines = build_qbox()

    assert result.returncode == 0, result.stdout
    qemu = tmp_path / "qbox" / "build" / "_deps" / "libqemu-src"
    for patch in QEMU_PATCHES:
        applied = [
            line
            for line in calls(lines, "git", "apply")
            if line.endswith(patch) and "--check" not in line
        ]
        assert len(applied) == 1, patch
        assert str(qemu) in applied[0].split()


def test_a_second_run_applies_no_patch_again(build_qbox):
    build_qbox()
    result, lines = build_qbox()

    assert result.returncode == 0, result.stdout
    applied = [
        line for line in calls(lines, "git", "apply") if "--check" not in line
    ]
    assert len(applied) == len(QBOX_PATCHES) + len(QEMU_PATCHES)


def test_the_jobs_option_is_how_many_files_are_compiled_at_once(build_qbox):
    result, lines = build_qbox("--jobs", "3")

    assert result.returncode == 0, result.stdout
    assert calls(lines, "cmake", "--build", "--parallel", "3")


def test_a_missing_library_stops_the_build_and_the_output_names_its_package(
    build_qbox,
):
    result, lines = build_qbox(missing="pixman-1")

    assert result.returncode != 0
    assert "libpixman-1-dev" in result.stdout
    assert not calls(lines, "cmake")


def test_an_unknown_option_is_refused_with_the_usage(build_qbox):
    result, _ = build_qbox("--spam")

    assert result.returncode == 2
    assert "usage: tools/build_qbox.py" in result.stdout


def test_a_missing_library_is_also_named_as_the_homebrew_formula_a_mac_installs(
    build_qbox,
):
    result, lines = build_qbox(missing="pixman-1")

    assert result.returncode != 0
    assert "brew install pixman" in result.stdout
    assert not calls(lines, "cmake")


@pytest.mark.parametrize(
    ("library", "package"), [("sdl2", "libsdl2-dev"), ("slirp", "libslirp-dev")]
)
def test_qemus_sdl_and_slirp_are_among_the_libraries_the_build_stops_without(
    build_qbox, library, package
):
    result, lines = build_qbox(missing=library)

    assert result.returncode != 0
    assert package in result.stdout
    assert not calls(lines, "cmake")


def test_qboxs_own_tests_are_not_built_since_socpuppet_holds_its_cpu_to_its_own(
    build_qbox,
):
    result, lines = build_qbox()

    assert result.returncode == 0, result.stdout
    (configure,) = calls(lines, "cmake", "-S")
    assert "-DBUILD_TESTING=OFF" in configure.split()


def test_a_configure_that_could_not_fetch_cpm_says_to_check_the_network(
    build_qbox,
):
    result, _ = build_qbox(configure="offline")

    assert result.returncode != 0
    assert "tools/doctor.py network" in result.stdout


def test_a_configure_that_could_not_fetch_cpm_once_is_tried_again_and_the_build_goes_on(
    build_qbox,
):
    result, lines = build_qbox(configure="offline once")

    assert result.returncode == 0, result.stdout
    assert len(calls(lines, "cmake", "-S")) == 2


def test_a_configure_that_fails_otherwise_says_nothing_of_the_network(
    build_qbox,
):
    result, _ = build_qbox(configure="fails")

    assert result.returncode != 0
    assert "network" not in result.stdout


def test_a_configure_that_fails_otherwise_is_not_tried_again(build_qbox):
    _, lines = build_qbox(configure="fails")

    assert len(calls(lines, "cmake", "-S")) == 1


@pytest.mark.parametrize("patch", QBOX_PATCHES)
def test_when_a_patch_neither_applies_nor_reverses_the_build_stops_and_says_to_run_cleanup_repair(
    build_qbox, patch
):
    result, lines = build_qbox(broken=patch)

    assert result.returncode != 0
    assert patch in result.stdout
    assert "uv run python tools/cleanup.py repair" in result.stdout
    assert not calls(lines, "cmake")
