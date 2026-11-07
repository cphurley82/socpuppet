"""tools/manylinux_packages.sh: what a Linux wheel's build installs first.

cibuildwheel runs it once in its manylinux container, before the first
wheel (pyproject.toml's before-all). A stand-in for dnf on the PATH fails
as many times as a test says, and writes down what it was asked.
"""

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "manylinux_packages.sh"


class TestWhenAMirrorFailsAFewTimes:
    def test_the_packages_are_installed_after_a_fresh_start_each_time(
        self, tmp_path
    ):
        ran = run_with_a_dnf_that_fails(tmp_path, times=2)

        assert ran.returncode == 0, ran.stderr
        assert asked_of_dnf(tmp_path) == [
            "install -y zlib-devel epel-release",
            "clean all",
            "install -y zlib-devel epel-release",
            "clean all",
            "install -y zlib-devel epel-release",
            "install -y ccache",
        ]


class TestWhenAMirrorFailsEveryTime:
    def test_the_script_fails_after_five_tries_and_says_why(self, tmp_path):
        ran = run_with_a_dnf_that_fails(tmp_path, times=1000)

        assert ran.returncode != 0
        assert asked_of_dnf(tmp_path) == [
            *["install -y zlib-devel epel-release", "clean all"] * 4,
            "install -y zlib-devel epel-release",
        ]
        assert "dnf failed 5 times" in ran.stderr


def run_with_a_dnf_that_fails(tmp_path, times):
    """Run the script with a dnf whose first `times` installs fail.

    `sleep` is a stand-in too, which returns at once.
    """
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    a_program(
        bin_directory / "dnf",
        f"""
        echo "$*" >> {tmp_path / "asked"}
        [ "$1" = install ] || exit 0
        echo spam >> {tmp_path / "installs"}
        [ "$(wc -l < {tmp_path / "installs"})" -gt {times} ]
        """,
    )
    a_program(bin_directory / "sleep", "exit 0")
    return subprocess.run(
        ["sh", str(SCRIPT)],
        env={**os.environ, "PATH": f"{bin_directory}{os.pathsep}/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


def a_program(path, script):
    """A shell script at `path` that does what `script` says."""
    lines = (line.strip() for line in script.strip().splitlines())
    path.write_text("#!/bin/sh\n" + "\n".join(lines) + "\n")
    path.chmod(0o755)


def asked_of_dnf(tmp_path):
    """What the stand-in dnf was asked, one line for each time."""
    return (tmp_path / "asked").read_text().splitlines()
