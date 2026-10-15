"""tools/build_qbox.sh, which builds QBox for the qbox_cpu.

The script is run for real, with stand-ins for git, cmake and the rest on
its path. Each stand-in writes the command it was given to a log, and git's
keeps track of which patches it has applied, so the tests can say what the
script asked for without fetching or building QEMU.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "build_qbox.sh"
PIN = "4d63017c88a147839d49028d0c60666d691460cc"
QBOX_PATCHES = sorted(p.name for p in (REPO / "cmake/patches").glob("qbox-*"))
QEMU_PATCHES = sorted(
    p.name for p in (REPO / "cmake/patches").glob("libqemu-*")
)

# A git that clones by making the directory, and applies a patch by noting
# its name: `apply --check` passes for a patch not yet applied, and
# `apply --reverse --check` for one that has been.
GIT = """
import os, sys
from pathlib import Path
args = sys.argv[1:]
tree = Path.cwd()
if args[0] == "-C":
    tree, args = Path(args[1]), args[2:]
if args[0] == "clone":
    (Path(args[-1]) / ".git").mkdir(parents=True)
elif args[:2] == ["rev-parse", "HEAD"]:
    head = tree / ".git" / "HEAD"
    print(head.read_text() if head.exists() else "0" * 40)
elif args[0] == "checkout":
    (tree / ".git" / "HEAD").write_text(args[-1])
elif args[0] == "apply":
    applied = tree / ".git" / "applied"
    done = applied.read_text().split() if applied.exists() else []
    name = os.path.basename(args[-1])
    if "--reverse" in args:
        sys.exit(0 if name in done else 1)
    if "--check" in args:
        sys.exit(1 if name in done else 0)
    applied.write_text(" ".join([*done, name]))
"""

# A cmake that, configuring, leaves QEMU's source where QBox's fetch would.
CMAKE = """
from pathlib import Path
if "-B" in sys.argv:
    build = Path(sys.argv[sys.argv.index("-B") + 1])
    (build / "_deps" / "libqemu-src" / ".git").mkdir(parents=True, exist_ok=True)
"""

# What the stand-in for pkg-config does not have, from the environment.
PKG_CONFIG = """
import os, sys
sys.exit(1 if sys.argv[-1] in os.environ.get("MISSING", "").split() else 0)
"""


@pytest.fixture
def build_qbox(tmp_path):
    """Run the script with the stand-ins; returns (result, log)."""
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = tmp_path / "log"
    logger = f"open({str(log)!r}, 'a').write(' '.join(sys.argv) + '\\n')\n"
    programs = {
        "git": GIT,
        "cmake": CMAKE,
        "pkg-config": PKG_CONFIG,
        "ninja": "",
        "meson": "",
        "bison": "",
        "flex": "",
    }
    for name, body in programs.items():
        program = bin_directory / name
        program.write_text(f"#!{sys.executable}\nimport sys\n{logger}{body}")
        program.chmod(0o755)

    def run(*args, missing=""):
        result = subprocess.run(
            ["bash", str(SCRIPT), "--root", str(tmp_path / "qbox"), *args],
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


def calls(lines, program, *words):
    """The logged commands of `program` that contain every one of `words`."""
    return [
        line
        for line in lines
        if Path(line.split()[0]).name == program
        and all(word in line.split() for word in words)
    ]


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
    assert "usage: tools/build_qbox.sh" in result.stdout


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
