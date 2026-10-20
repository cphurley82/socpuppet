"""firmware/twister.py, which runs twister on socpuppet's boards.

The tool is run for real in a throwaway copy of what it reads, with
build/firmware holding a stand-in for Zephyr's twister and for the venv's
Python that runs it, and a stand-in Python for the venv socpuppet was built
for. Each logs what it was asked, so the tests can say how twister was run
without building or booting anything.
"""

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "firmware" / "twister.py"
VERSIONS = REPO / "firmware" / "versions.toml"
BUILD = REPO / "firmware" / "build.py"

# A Python, for either venv: it logs what it was asked to run, and where
# it was asked to put its output, and answers -c with success.
PYTHON = r"""
import json, os, sys
with open(os.environ["LOG"], "a") as log:
    log.write(json.dumps({"python": sys.argv[0], "args": sys.argv[1:], "env": {
        k: os.environ.get(k, "") for k in
        ("ZEPHYR_BASE", "ZEPHYR_EXTRA_MODULES", "SOCPUPPET_FIRMWARE_DIR",
         "ZEPHYR_SDK_INSTALL_DIR")
    }}) + "\n")
"""

SUITES = """\
# A comment, and a blank line, which are not suites.

tests/kernel/spam
tests/kernel/eggs
tests/arch/riscv/fatal -K
firmware/watchdog/tests -p socpuppet_host
"""

# socpuppet's boards, which are every board twister runs on.
BOARDS = sorted(
    board.name
    for board in (
        REPO / "python" / "socpuppet" / "zephyr_module" / "boards" / "socpuppet"
    ).iterdir()
    if board.is_dir()
)

# On an Intel Mac the tool runs itself in Docker, which these tests do not
# stand in for.
pytestmark = pytest.mark.skipif(
    (platform.system(), platform.machine()) == ("Darwin", "x86_64"),
    reason="an Intel Mac runs twister in Docker",
)


class Twister:
    """The throwaway repository, and the log of what twister was asked."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "repo"
        self.log = tmp_path / "log"
        self.project = tmp_path / "project-venv"
        firmware = self.root / "firmware"
        firmware.mkdir(parents=True)
        shutil.copy(TOOL, firmware / "twister.py")
        shutil.copy(BUILD, firmware / "build.py")
        shutil.copy(VERSIONS, firmware / "versions.toml")
        (firmware / "twister-suites.txt").write_text(SUITES)
        (firmware / "twister-quarantine.yaml").write_text("[]\n")
        (firmware / "twister-requirements.txt").write_text("spam\n")
        sdk_version = tomllib.loads(VERSIONS.read_text())["sdk"]["version"]
        self.out = self.root / "build" / "firmware"
        # Where firmware/build.py keeps this machine's tools.
        self.machine = self.out / this_machine()
        self.sdk = self.machine / f"zephyr-sdk-{sdk_version}"
        # What the tool looks for before it runs twister.
        self.prerequisites = {
            "zephyr": self.out / "zephyr",
            "venv": self.machine / "venv" / "bin" / "python",
            "sdk": self.sdk,
            "rom_rv32": self.out / "rom_rv32.elf",
            "rom_rv64": self.out / "rom_rv64.elf",
        }
        self.python(self.out / "zephyr" / "scripts" / "twister")
        self.python(self.machine / "venv" / "bin" / "python")
        self.sdk.mkdir(parents=True)
        for rom in ("rom_rv32.elf", "rom_rv64.elf"):
            (self.out / rom).touch()
        self.python(self.project / "bin" / "python")

    def python(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!{sys.executable}\n{PYTHON}")
        path.chmod(0o755)

    def run(self, *args):
        result = subprocess.run(
            [sys.executable, str(self.root / "firmware" / "twister.py"), *args],
            cwd=self.root,
            env={
                **os.environ,
                "LOG": str(self.log),
                "UV_PROJECT_ENVIRONMENT": str(self.project),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        return result

    def runs(self):
        """Each run of twister: its arguments after the script's path."""
        return [call["args"][1:] for call in self.twisters()]

    def environments(self):
        """What each run of twister was told by its environment."""
        return [call["env"] for call in self.twisters()]

    def twisters(self):
        if not self.log.exists():
            return []
        lines = self.log.read_text().splitlines()
        calls = [json.loads(line) for line in lines]
        return [
            call
            for call in calls
            if call["args"] and call["args"][0].endswith("scripts/twister")
        ]

    def run_of_the_suites_with_no_flags(self):
        (run,) = [
            r
            for r in self.runs()
            if not values(r, "-K") and len(values(r, "-T")) == 2
        ]
        return run


@pytest.fixture
def twister(tmp_path):
    return Twister(tmp_path)


def test_the_suites_with_no_flags_run_together_and_each_flagged_one_alone(
    twister,
):
    result = twister.run("--suites")

    assert result.returncode == 0, result.stdout
    roots = [values(run, "-T") for run in twister.runs()]
    assert sorted(len(each) for each in roots) == [1, 1, 2]
    together = next(each for each in roots if len(each) == 2)
    assert [Path(root).name for root in together] == ["spam", "eggs"]


def test_a_flagged_suite_gets_its_flags_and_no_other_suites(twister):
    twister.run("--suites")

    (fatal,) = [run for run in twister.runs() if "-K" in run]
    assert [Path(root).name for root in values(fatal, "-T")] == ["fatal"]


def test_with_no_board_given_every_board_is_named(twister):
    twister.run("--suites")

    run = twister.run_of_the_suites_with_no_flags()
    assert sorted(values(run, "-p")) == BOARDS


def test_a_board_the_command_names_is_the_only_one(twister):
    twister.run("--suites", "-p", "socpuppet_ssd")

    run = twister.run_of_the_suites_with_no_flags()
    assert values(run, "-p") == ["socpuppet_ssd"]


def test_a_relative_suite_is_zephyrs_unless_it_is_under_firmware_or_python(
    twister,
):
    twister.run("--suites")

    roots = [root for run in twister.runs() for root in values(run, "-T")]
    zephyr = twister.out / "zephyr"
    assert str(zephyr / "tests" / "kernel" / "spam") in roots
    assert str(twister.root / "firmware" / "watchdog" / "tests") in roots


def test_a_suite_given_by_hand_is_resolved_as_the_lists_are(twister):
    twister.run("-T", "tests/kernel/sleep", "-T", "python/spam")

    (run,) = twister.runs()
    assert values(run, "-T") == [
        str(twister.out / "zephyr" / "tests" / "kernel" / "sleep"),
        str(twister.root / "python" / "spam"),
    ]


def test_each_run_keeps_its_verdicts_in_a_directory_of_its_own(twister):
    twister.run("--suites")

    outdirs = [only(run, "--outdir") for run in twister.runs()]
    out = twister.root / "build" / "twister" / "out"
    assert sorted(Path(each).parent for each in outdirs) == [out] * 3
    assert len(set(outdirs)) == 3


@pytest.mark.parametrize(
    "missing", ["zephyr", "venv", "sdk", "rom_rv32", "rom_rv64"]
)
def test_a_prerequisite_that_is_missing_is_named_and_nothing_runs(
    twister, missing
):
    path = twister.prerequisites[missing]
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()

    result = twister.run("--suites")

    assert result.returncode == 1
    assert str(path.relative_to(twister.out)) in result.stdout
    assert "uv run firmware/build.py" in result.stdout
    assert twister.runs() == []


def test_twister_finds_zephyr_our_boards_and_the_boot_roms(twister):
    twister.run("-T", "tests/kernel/sleep")

    (env,) = twister.environments()
    assert env["ZEPHYR_BASE"] == str(twister.out / "zephyr")
    assert env["ZEPHYR_EXTRA_MODULES"] == str(
        twister.root / "python" / "socpuppet" / "zephyr_module"
    )
    assert env["SOCPUPPET_FIRMWARE_DIR"] == str(twister.out)


def test_twister_is_run_with_this_machines_sdk_and_venv(twister):
    twister.run("-T", "tests/kernel/sleep")

    (call,) = twister.twisters()
    assert call["env"]["ZEPHYR_SDK_INSTALL_DIR"] == str(twister.sdk)
    assert call["python"] == str(twister.machine / "venv" / "bin" / "python")


def this_machine():
    """The SDK's name for the machine the tests run on, as build.py has it."""
    spec = importlib.util.spec_from_file_location("build", BUILD)
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    return build.sdk_host()


def values(run, option):
    """What each `option VALUE` of a run gave, in order."""
    return [run[i + 1] for i, word in enumerate(run[:-1]) if word == option]


def only(run, option):
    """The value of an option a run was given once."""
    (value,) = values(run, option)
    return value
