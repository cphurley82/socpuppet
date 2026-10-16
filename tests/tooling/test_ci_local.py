"""tools/ci_local.sh, which runs the CI workflows' steps on this machine.

The script is run for real in a throwaway copy of the repository, with
stand-ins for uv, docker and the firmware scripts. Each stand-in writes the
command it was given to a log, so the tests can say what the script ran, and
in what order, without building anything.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "ci_local.sh"

DEPENDENCIES = """\
FetchContent_Declare(spam
  GIT_REPOSITORY https://example.invalid/spam.git
)
FetchContent_Declare(eggs
  GIT_REPOSITORY https://example.invalid/eggs.git
  PATCH_COMMAND git apply ${CMAKE_SOURCE_DIR}/cmake/patches/eggs-fix.patch
)
FetchContent_Declare(Ham_Core
  PATCH_COMMAND git apply ${CMAKE_SOURCE_DIR}/cmake/patches/ham-fix.patch
)
"""

# A program that logs its command line and exits with the status the test
# asked for: FAIL_ON names a word, and a command that holds it fails.
STAND_IN = """\
import os, sys
open(os.environ["LOG"], "a").write(os.path.basename(sys.argv[0]) + " "
                                   + " ".join(sys.argv[1:]) + "\\n")
open(os.environ["LOG"] + ".require", "a").write(
    os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE", "") + "\\n")
sys.exit(1 if os.environ.get("FAIL_ON", "@") in sys.argv[1:] else 0)
"""


def write_stand_in(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{STAND_IN}")
    path.chmod(0o755)


@pytest.fixture
def ci_local(tmp_path):
    """Run the script in a copy of the repo; returns run(*args, **env)."""
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "tools" / "ci_local.sh")
    (root / "cmake" / "patches").mkdir(parents=True)
    (root / "cmake" / "Dependencies.cmake").write_text(DEPENDENCIES)
    (root / "cmake" / "patches" / "eggs-fix.patch").write_text("one\n")
    (root / "tools" / "build_qbox.sh").write_text("# the pin\n")
    (root / ".python-version").write_text("3.13\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for script in ("firmware/build.sh", "firmware/twister.sh"):
        write_stand_in(root / script)
    bin_directory = tmp_path / "bin"
    for program in ("uv", "uvx", "docker"):
        write_stand_in(bin_directory / program)
    log = tmp_path / "log"

    def run(*args, **env):
        result = subprocess.run(
            ["bash", str(root / "tools" / "ci_local.sh"), *args],
            cwd=root,
            env={
                # Less what the script is to set itself, which CI's own test
                # job has set around the tests already.
                **{
                    name: value
                    for name, value in os.environ.items()
                    if name != "SOCPUPPET_REQUIRE_FIRMWARE"
                },
                "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
                "LOG": str(log),
                **env,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        lines = log.read_text().splitlines() if log.exists() else []
        return result, lines

    run.root = root
    return run


def make_dependency(root, tree, name):
    for suffix in ("src", "build", "subbuild"):
        directory = root / tree / "_deps" / f"{name}-{suffix}"
        directory.mkdir(parents=True)
        (directory / "file").write_text("old\n")


def stamp_of(root):
    """What the script writes: a hash of what the patches are made from."""
    digest = hashlib.sha256()
    for path in (
        root / "cmake" / "Dependencies.cmake",
        *sorted((root / "cmake" / "patches").glob("*")),
        root / "tools" / "build_qbox.sh",
    ):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_asking_for_one_job_runs_that_job_and_no_other(ci_local):
    result, lines = ci_local("lint")

    assert result.returncode == 0, result.stdout
    assert lines == ["uv sync", "uv run python tools/lint.py"]


def test_a_job_that_fails_is_named_in_the_summary_and_the_exit_status_says_so(
    ci_local,
):
    result, _ = ci_local("lint", "firmware", FAIL_ON="tools/lint.py")

    assert result.returncode != 0
    assert "❌ lint" in result.stdout
    assert "✅ firmware" in result.stdout


def test_a_step_that_fails_ends_its_job_and_the_jobs_after_it_still_run(
    ci_local,
):
    result, lines = ci_local("lint", "firmware", FAIL_ON="sync")

    assert result.returncode != 0
    assert lines[0] == "uv sync"
    assert lines[1].startswith("build.sh")
    assert len(lines) == 2


def test_the_test_job_configures_builds_and_tests_the_dev_tree(ci_local):
    result, lines = ci_local("test")

    assert result.returncode == 0, result.stdout
    assert lines == [
        "uv run cmake --preset dev",
        "uv run cmake --build --preset dev",
        "uv run ctest --preset dev",
    ]


def test_the_test_job_makes_a_missing_firmware_image_fail_its_boot_test(
    ci_local, tmp_path
):
    ci_local("test")

    required = (tmp_path / "log.require").read_text().splitlines()
    assert required == ["", "", "1"]


def test_when_the_patches_have_changed_the_patched_dependencies_are_dropped(
    ci_local,
):
    root = ci_local.root
    build = root / "build"
    build.mkdir()
    (build / ".ci-local-patches").write_text("an older set of patches\n")
    make_dependency(root, "build/dev", "eggs")
    make_dependency(root, "build/dev", "ham_core")
    make_dependency(root, "build/dev", "spam")
    make_dependency(root, "build/qbox-dev", "eggs")
    make_dependency(root, "build/qbox/build", "rpclib")
    make_dependency(root, "build/qbox/build", "libqemu")

    result, _ = ci_local("lint")

    assert result.returncode == 0, result.stdout
    for gone in (
        "build/dev/_deps/eggs-src",
        "build/dev/_deps/ham_core-build",
        "build/qbox-dev/_deps/eggs-subbuild",
        "build/qbox/build/_deps/rpclib-src",
    ):
        assert not (root / gone).exists(), gone
    # What is not patched is slow to build, and is left alone.
    assert (root / "build/dev/_deps/spam-src/file").exists()
    assert (root / "build/qbox/build/_deps/libqemu-src/file").exists()


def test_when_the_patches_are_the_same_nothing_is_dropped(ci_local):
    root = ci_local.root
    (root / "build").mkdir()
    (root / "build" / ".ci-local-patches").write_text(stamp_of(root) + "\n")
    make_dependency(root, "build/dev", "eggs")

    result, _ = ci_local("lint")

    assert result.returncode == 0, result.stdout
    assert (root / "build/dev/_deps/eggs-src/file").exists()


def test_a_tree_with_no_stamp_is_taken_to_be_stale(ci_local):
    root = ci_local.root
    make_dependency(root, "build/dev", "eggs")

    ci_local("lint")

    assert not (root / "build/dev/_deps/eggs-src").exists()
    stamp = (root / "build" / ".ci-local-patches").read_text().strip()
    assert stamp == stamp_of(root)


def test_clean_drops_the_patched_dependencies_though_the_patches_are_the_same(
    ci_local,
):
    root = ci_local.root
    (root / "build").mkdir()
    (root / "build" / ".ci-local-patches").write_text(stamp_of(root) + "\n")
    make_dependency(root, "build/dev", "eggs")

    ci_local("--clean", "lint")

    assert not (root / "build/dev/_deps/eggs-src").exists()


def test_the_wheel_job_is_skipped_with_its_reason_when_docker_is_not_there(
    ci_local, tmp_path
):
    # A PATH of its own: the tools the script uses, and not docker.
    bin_directory = tmp_path / "no-docker"
    bin_directory.mkdir()
    for program in [
        "bash",
        "env",
        "git",
        "awk",
        "sort",
        "rm",
        "cat",
        "sha256sum",
        "cut",
        "tr",
        "mkdir",
        "dirname",
        "uname",
        "sed",
        "tail",
        "mktemp",
        "xargs",
        "cp",
        "printf",
        "wc",
    ]:
        found = shutil.which(program)
        if found:
            (bin_directory / program).symlink_to(found)

    result, lines = ci_local("wheel", PATH=str(bin_directory))

    assert result.returncode == 0, result.stdout
    assert "Docker" in result.stdout
    assert lines == []


def test_the_wheel_job_is_skipped_when_docker_is_there_but_cannot_be_reached(
    ci_local,
):
    result, lines = ci_local("wheel", FAIL_ON="info")

    assert result.returncode == 0, result.stdout
    assert "docker info" in result.stdout
    assert lines == ["docker info"]


def test_an_unknown_job_is_refused_and_the_usage_names_the_jobs(ci_local):
    result, lines = ci_local("spam")

    assert result.returncode == 2
    assert "lint" in result.stdout
    assert lines == []
