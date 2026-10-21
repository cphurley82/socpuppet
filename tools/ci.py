"""Run CI's jobs: those that can run on this machine, or one in CI.

CI's jobs are in two tiers: the quick tier, on every push and pull request
(ci.yml), and the nightly tier (nightly.yml), which runs everything on
every machine.

Usage:
  uv run python tools/ci.py [-j N] [JOB ...]    the nightly tier's jobs that
                                                can run here, or those named
  uv run python tools/ci.py --quick [-j N]      the quick tier's, as a push
  uv run python tools/ci.py --list              the jobs, and how to run each
  uv run python tools/ci.py run JOB [JOB ...]   in CI

Here, up to three jobs run at a time, short ones first, and each step's
output is kept in build/ci/. A job named without the jobs it needs takes
what they make as made already.

`run` is what each job of both workflows calls: it runs the steps
of the jobs named, in order, with their output in CI's log, and stops at the
first that fails.
"""

import argparse
import contextlib
import enum
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

# The top of the repository, which every step is run from.
REPO = Path(__file__).resolve().parents[1]
# Where a run on this machine keeps each step's output.
LOGS = REPO / "build" / "ci"
# Where the wheel job leaves the wheels, from the top of the repository.
WHEELHOUSE = "build/wheelhouse"
# Where a wheel built here on Linux keeps its container's compiler cache.
CCACHE = "build/ccache"
ON_LINUX = platform.system() == "Linux"
# Where firmware/twister.py runs in the devcontainer's image, by its own test
# of the machine, on a socpuppet built there for Linux, which has no QBox.
INTEL_MAC = (platform.system(), platform.machine()) == ("Darwin", "x86_64")


class Mode(enum.Enum):
    """Where a job runs: here, or in CI."""

    HERE = enum.auto()
    CI = enum.auto()


class Tier(enum.Enum):
    """A tier of CI's jobs, by the workflow that runs it.

    The quick tier runs on every push and pull request, and leaves out what
    takes longest. The nightly tier is every job but test-quick, on every
    machine, and is what a run here runs unless asked otherwise.
    """

    QUICK = "ci.yml"
    NIGHTLY = "nightly.yml"


class NoMatch(Exception):
    """A step's file pattern that matches no file."""


@dataclass(frozen=True)
class Glob:
    """A pattern of paths from the top of the repository, in a command.

    It stands for the files it matches when its step starts, in order. One
    that matches none fails the step.
    """

    pattern: str

    def __str__(self) -> str:
        return self.pattern


@dataclass(frozen=True)
class Step:
    """One command of a job, and what it is called in the job's output."""

    label: str
    argv: tuple[str | Glob, ...]
    # Variables set for this step alone.
    env: Mapping[str, str] = field(default_factory=dict)

    def command(self) -> list[str]:
        """The command, with each pattern replaced by the files it matches.

        Raises NoMatch, naming the pattern, if one matches no file.
        """
        command = []
        for word in self.argv:
            if isinstance(word, str):
                command.append(word)
                continue
            matches = sorted(
                str(path.relative_to(REPO)) for path in REPO.glob(word.pattern)
            )
            if not matches:
                raise NoMatch(f"no file matches {word}")
            command.extend(matches)
        return command


@dataclass(frozen=True)
class Job:
    """One of CI's jobs: its name, what it is for, and its steps."""

    name: str
    blurb: str
    # Its steps, or what makes them for where it runs.
    steps: tuple[Step, ...] | Callable[[Mode], tuple[Step, ...]]
    # The tiers it is in: the quick, the nightly, or both.
    tiers: tuple[Tier, ...]
    # The jobs whose output this one reads, which come before it in JOBS.
    needs: tuple[str, ...] = ()
    # What it builds in, or writes to, that no other job may use while it
    # runs here: a build tree, or the extension every tree puts in
    # python/socpuppet.
    uses: tuple[str, ...] = ()
    # Whether it runs in Docker.
    docker: bool = False
    # Whether it configures build/dev with a preset other than dev, which
    # shares the tree. A run here configures it for dev again at the end.
    # What it built stays as it was until the next dev build: after the
    # coverage job, the extension in python/socpuppet is the one built to
    # measure coverage.
    reconfigures_dev: bool = False
    # Directories emptied before its steps, of what an earlier run left.
    fresh: tuple[str, ...] = ()
    # Directories made before its steps if they are not there, so that they
    # are the user's who runs it, and not the root of a container's.
    made: tuple[str, ...] = ()
    # What it needs of this machine, as the areas tools/doctor.py checks.
    # A job in Docker needs Docker too.
    areas: tuple[str, ...] = ()

    def every_area(self) -> tuple[str, ...]:
        """What it needs of this machine, Docker included."""
        return (*self.areas, "docker") if self.docker else self.areas

    def steps_for(self, mode: Mode) -> tuple[Step, ...]:
        """Its steps, where it runs."""
        return self.steps if isinstance(self.steps, tuple) else self.steps(mode)


# The Ubuntus the devcontainer jobs build in, in the devcontainer's image
# (tools/devcontainer.py --ubuntu): the default, the Dockerfile's
# ARG UBUNTU, and the oldest socpuppet supports.
UBUNTUS = ("26.04", "24.04")

# What configures the dev tree, and what builds it. A run here also
# configures build/dev for dev again with it, after a job that configured
# it with another preset.
CONFIGURE_DEV = ("uv", "run", "cmake", "--preset", "dev")
DEV_BUILD = (
    Step("configure", CONFIGURE_DEV),
    Step("build", ("uv", "run", "cmake", "--build", "--preset", "dev")),
)

# A missing firmware image fails its boot test instead of skipping it.
REQUIRE_FIRMWARE = {"SOCPUPPET_REQUIRE_FIRMWARE": "1"}


def tidy_steps(preset: str) -> tuple[Step, ...]:
    """Configure a tree, then run clang-tidy and the header check over it."""
    build = ("uv", "run", "cmake", "--build", "--preset", preset)
    return (
        Step("configure", ("uv", "run", "cmake", "--preset", preset)),
        Step("tidy", (*build, "--target", "tidy")),
        Step("check_headers", (*build, "--target", "check_headers")),
    )


def qbox_steps() -> tuple[Step, ...]:
    """Build and test the QBox tree, then run twister on the host board.

    On an Intel Mac, firmware/twister.py runs twister in the devcontainer's
    image, not natively: here that image's socpuppet is built for Linux,
    without QBox, which is built for the Mac; and CI's Intel Macs have no
    Docker. So a run there stops after the tests.
    """
    steps = (
        Step("configure", ("uv", "run", "cmake", "--preset", "qbox")),
        Step("build", ("uv", "run", "cmake", "--build", "--preset", "qbox")),
        Step(
            "ctest",
            ("uv", "run", "ctest", "--preset", "qbox"),
            env=REQUIRE_FIRMWARE,
        ),
    )
    if INTEL_MAC:
        return steps
    return (
        *steps,
        Step(
            "twister",
            (
                *("uv", "run", "firmware/twister.py", "--suites"),
                *("-p", "socpuppet_host"),
            ),
            env={"SOCPUPPET_CPU": "qbox_cpu"},
        ),
    )


def devcontainer_steps(ubuntu: str) -> tuple[Step, ...]:
    """Build the linux preset's tree in the image on `ubuntu`, and test it."""
    inside = ("tools/devcontainer.py", "--ubuntu", ubuntu, "uv", "run")
    return (
        Step("configure", (*inside, "cmake", "--preset", "linux")),
        Step("build", (*inside, "cmake", "--build", "--preset", "linux")),
        Step(
            "ctest",
            (*inside, "ctest", "--preset", "linux"),
            env=REQUIRE_FIRMWARE,
        ),
    )


def container_tree(ubuntu: str) -> str:
    """The linux preset's tree of `ubuntu`'s container, from the top.

    It is build/linux in the container, kept apart by tools/devcontainer.py.
    """
    return f"build/container/ubuntu-{ubuntu}/linux"


def wheel_steps(mode: Mode) -> tuple[Step, ...]:
    """Build the wheels, check what each holds, and install ours two ways.

    In CI, cibuildwheel builds every wheel pyproject.toml asks for, in the
    checkout, where the compiler cache is. Here it builds the one for this
    machine and the Python the tools are pinned to, from a source
    distribution: given a directory, it copies all of it into its
    container, build/ too. Ours is then installed with uv and with pip,
    away from the source tree, and boots the firmware.
    """
    python = (REPO / ".python-version").read_text().strip()
    tag = "cp" + python.replace(".", "")
    if mode is Mode.CI:
        build: tuple[Step, ...] = (
            Step(
                "cibuildwheel",
                ("uv", "run", "cibuildwheel", "--output-dir", WHEELHOUSE),
            ),
        )
    else:
        system = "manylinux" if ON_LINUX else "macosx"
        sdists = f"{WHEELHOUSE}/sdist"
        # test_wheel.py tests the same wheel below, with the firmware, which
        # cibuildwheel's own test has not got.
        env = {"CIBW_TEST_SKIP": "*"}
        if ON_LINUX:
            # The container is thrown away after each build, and its compiler
            # cache with it, so the cache is kept here, which it sees under
            # /host. It runs as root, so what it caches is left for anyone to
            # remove, and so for any user of this machine to write to.
            env |= {
                "CCACHE_DIR": f"/host{REPO}/{CCACHE}",
                "CCACHE_UMASK": "000",
            }
        build = (
            Step("sdist", ("uv", "build", "--sdist", "--out-dir", sdists)),
            Step(
                "cibuildwheel",
                (
                    *("uv", "run", "cibuildwheel"),
                    *("--only", f"{tag}-{system}_{platform.machine()}"),
                    *("--output-dir", WHEELHOUSE),
                    Glob(f"{sdists}/*.tar.gz"),
                ),
                env=env,
            ),
        )
    firmware = {
        **REQUIRE_FIRMWARE,
        "SOCPUPPET_FIRMWARE_DIR": str(REPO / "build" / "firmware"),
    }
    ours = Glob(f"{WHEELHOUSE}/*-{tag}-*.whl")
    return (
        *build,
        Step(
            "check_wheel",
            (
                "uv",
                "run",
                "python",
                "tools/check_wheel.py",
                Glob(f"{WHEELHOUSE}/*.whl"),
            ),
        ),
        Step(
            "test_wheel_uv", ("tools/test_wheel.py", "uv", ours), env=firmware
        ),
        Step(
            "test_wheel_pip", ("tools/test_wheel.py", "pip", ours), env=firmware
        ),
    )


# The jobs that build the firmware, every image of which the tests boot.
FIRMWARE = (
    "firmware-rom",
    "firmware-opensbi",
    "firmware-zephyr",
    "firmware-edk2",
    "firmware-linux",
)


# Short first: when two jobs could start, the one higher in the table does.
JOBS = [
    Job(
        "lint",
        "formatting and static checks on every file",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        steps=(Step("lint", ("uv", "run", "python", "tools/lint.py")),),
    ),
    Job(
        "fetch-sdk",
        "fetch the Zephyr SDK's RISC-V toolchain",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        steps=(Step("fetch", ("uv", "run", "firmware/build.py", "sdk")),),
        areas=("firmware",),
    ),
    Job(
        "fetch-llvm",
        "fetch the Zephyr SDK's LLVM, which builds OpenSBI and EDK2",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        steps=(Step("fetch", ("uv", "run", "firmware/build.py", "llvm")),),
        areas=("firmware",),
    ),
    Job(
        "fetch-zephyr",
        "fetch Zephyr, and make a venv for its build scripts and twister",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        steps=(
            Step("fetch", ("uv", "run", "firmware/build.py", "zephyr-tree")),
        ),
        areas=("firmware",),
    ),
    Job(
        "firmware-rom",
        "build the boot ROMs, and the payload of ours for OpenSBI",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        needs=("fetch-sdk",),
        steps=(Step("build", ("uv", "run", "firmware/build.py", "rom")),),
        areas=("firmware",),
    ),
    Job(
        "firmware-opensbi",
        "build OpenSBI for the host",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        needs=("fetch-llvm",),
        steps=(Step("build", ("uv", "run", "firmware/build.py", "opensbi")),),
        areas=("firmware",),
    ),
    Job(
        "firmware-zephyr",
        "build Zephyr's images for the boards",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        needs=("fetch-sdk", "fetch-zephyr"),
        steps=(Step("build", ("uv", "run", "firmware/build.py", "zephyr")),),
        areas=("firmware",),
    ),
    Job(
        "firmware-edk2",
        "build EDK2, UEFI, for the host",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        needs=("fetch-llvm",),
        steps=(Step("build", ("uv", "run", "firmware/build.py", "edk2")),),
        areas=("firmware", "edk2"),
    ),
    Job(
        "firmware-linux",
        "build Linux, a stock kernel, for the host",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        needs=("fetch-llvm",),
        steps=(Step("build", ("uv", "run", "firmware/build.py", "linux")),),
        areas=("firmware", "linux"),
    ),
    Job(
        "test",
        "build the dev tree and run every test",
        tiers=(Tier.NIGHTLY,),
        needs=FIRMWARE,
        uses=("build/dev", "extension"),
        steps=(
            *DEV_BUILD,
            Step(
                "ctest",
                ("uv", "run", "ctest", "--preset", "dev"),
                env=REQUIRE_FIRMWARE,
            ),
        ),
        areas=("build",),
    ),
    Job(
        "test-quick",
        "build the dev tree and run every test but the long ones",
        tiers=(Tier.QUICK,),
        needs=FIRMWARE,
        uses=("build/dev", "extension"),
        steps=(
            *DEV_BUILD,
            # The quick preset leaves out the tests marked long.
            Step(
                "ctest",
                ("uv", "run", "ctest", "--preset", "quick"),
                env=REQUIRE_FIRMWARE,
            ),
        ),
        areas=("build",),
    ),
    Job(
        "on-demand",
        "build the dev tree and run the tests too long for every run",
        tiers=(Tier.NIGHTLY,),
        needs=FIRMWARE,
        uses=("build/dev", "extension"),
        steps=(
            *DEV_BUILD,
            # -m picks out the tests marked on_demand, and
            # SOCPUPPET_ON_DEMAND=1 stops socpuppet's plugin skipping them.
            Step(
                "pytest",
                ("uv", "run", "pytest", "-m", "on_demand"),
                env={**REQUIRE_FIRMWARE, "SOCPUPPET_ON_DEMAND": "1"},
            ),
        ),
        areas=("build",),
    ),
    Job(
        "tidy",
        "clang-tidy over our C++, and each header compiled on its own",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        steps=tidy_steps("dev"),
        uses=("build/dev",),
        # clang-tidy reads the compile commands of this machine's compiler,
        # and its standard library: GCC's and libstdc++ on Linux, Apple
        # clang's and the SDK's libc++ on a Mac. So each system's run checks
        # our code the way that system compiles it.
        areas=("build",),
    ),
    Job(
        "twister",
        "Zephyr's test suites, and ours, on every board, run by twister",
        tiers=(Tier.NIGHTLY,),
        # Twister builds its own images, with Zephyr and the SDK, and each
        # boots from the ROM.
        needs=("fetch-sdk", "fetch-zephyr", "firmware-rom"),
        steps=(
            *DEV_BUILD,
            # The tests that read Zephyr's tree, which only this job has.
            # One directory to a run of pytest, as ctest has it: each has
            # a conftest.py of its own.
            Step(
                "boards",
                ("uv", "run", "pytest", "tests/python/test_twister_boards.py"),
            ),
            Step(
                "tooling",
                ("uv", "run", "pytest", "tests/tooling", "-k", "twister"),
            ),
            Step("twister", ("uv", "run", "firmware/twister.py", "--suites")),
        ),
        uses=("build/dev", "extension", "build/twister"),
        areas=("build",),
    ),
    Job(
        "coverage",
        "which lines of our C++ and Python the tests run, against a floor",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        steps=(
            Step("configure", ("uv", "run", "cmake", "--preset", "coverage")),
            Step(
                "coverage",
                (
                    *("uv", "run", "cmake", "--build", "--preset", "coverage"),
                    *("--target", "coverage"),
                ),
            ),
        ),
        uses=("build/dev", "extension"),
        reconfigures_dev=True,
        areas=("build",),
    ),
    Job(
        "sanitizers",
        "the C++ tests, built to stop at a memory error or undefined behavior",
        tiers=(Tier.QUICK, Tier.NIGHTLY),
        steps=(
            Step("configure", ("uv", "run", "cmake", "--preset", "asan")),
            Step(
                "build", ("uv", "run", "cmake", "--build", "--preset", "asan")
            ),
            Step("ctest", ("uv", "run", "ctest", "--preset", "asan")),
        ),
        uses=("build/dev", "extension"),
        reconfigures_dev=True,
        areas=("build",),
    ),
    Job(
        "qbox-build",
        "build QBox, QEMU in SystemC, for the second hart",
        tiers=(Tier.NIGHTLY,),
        steps=(Step("build", ("uv", "run", "tools/build_qbox.py")),),
        uses=("build/qbox",),
        areas=("build", "qbox", "network"),
    ),
    Job(
        "qbox-tidy",
        "clang-tidy over the QBox adapter, which the dev tree leaves out",
        tiers=(Tier.NIGHTLY,),
        needs=("qbox-build",),
        steps=tidy_steps("qbox"),
        uses=("build/qbox-dev",),
        areas=("build",),
    ),
    Job(
        "qbox",
        "build and test with QBox's CPU as the second hart, then twister on it",
        tiers=(Tier.NIGHTLY,),
        needs=("fetch-sdk", "fetch-zephyr", *FIRMWARE, "qbox-build"),
        steps=qbox_steps(),
        uses=("build/qbox-dev", "extension", "build/twister"),
        areas=("build",),
    ),
    Job(
        "wheel",
        "build the wheels a user installs, and test one installed two ways",
        tiers=(Tier.NIGHTLY,),
        needs=FIRMWARE,
        steps=wheel_steps,
        fresh=(WHEELHOUSE,),
        made=(CCACHE,) if ON_LINUX else (),
        # cibuildwheel builds Linux's wheels in a manylinux container, and
        # a Mac's here. Each fetches its build's packages from PyPI.
        docker=ON_LINUX,
        areas=("network",) if ON_LINUX else ("build", "network", "wheel"),
    ),
    *(
        Job(
            f"devcontainer-{ubuntu.replace('.', '-')}",
            f"build and test in the devcontainer's image on Ubuntu {ubuntu}",
            tiers=(Tier.NIGHTLY,),
            needs=FIRMWARE,
            # In the linux preset's tree, which the container keeps apart for
            # each Ubuntu, so that the host's own build/dev is left alone.
            steps=devcontainer_steps(ubuntu),
            uses=(container_tree(ubuntu), "extension"),
            docker=True,
        )
        for ubuntu in UBUNTUS
    ),
]


JOBS_BY_NAME = {job.name: job for job in JOBS}
# The longest job's name, which the others are padded to in the output.
NAME_WIDTH = max(len(job.name) for job in JOBS)


def main() -> int:
    """Run the jobs asked for. Returns the exit status."""
    # A line is shown as soon as it is printed, before a step's own output.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    arguments = sys.argv[1:]
    # `run` is matched by hand: argparse cannot have a subcommand next to
    # job names that may be left out.
    if arguments[:1] == ["run"]:
        return run_for_ci(parse_run(arguments[1:]).jobs)
    args = parse_here(arguments)
    if args.list:
        list_jobs(args.docker)
        return 0
    tier = Tier.QUICK if args.quick else Tier.NIGHTLY
    return run_here(args.jobs, tier, args.parallel, args.docker, args.clean)


def parse_here(arguments: list[str]) -> argparse.Namespace:
    """What was asked of a run on this machine."""
    parser = argparse.ArgumentParser(
        prog="tools/ci.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "jobs",
        nargs="*",
        choices=list(JOBS_BY_NAME),
        metavar="job",
        help="run only these (default: every job of the nightly tier that "
        "can run here): "
        "%(choices)s",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="run the quick tier's jobs, which CI runs on every push "
        f"({Tier.QUICK.value}), and not the nightly tier's "
        f"({Tier.NIGHTLY.value})",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="run the jobs in Docker too: "
        + ", ".join(job.name for job in JOBS if job.docker),
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="drop the patched dependencies first, to fetch them again",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the jobs, and how to run each here, and run none",
    )
    parser.add_argument(
        "-j",
        dest="parallel",
        type=at_least_one,
        default=3,
        metavar="N",
        help="run up to N jobs at once (default: %(default)s)",
    )
    args = parser.parse_args(arguments)
    if args.quick and args.jobs:
        parser.error(
            "--quick runs the quick tier's jobs, not jobs named ("
            + " ".join(args.jobs)
            + "): leave out --quick to run those, or the names to run the "
            "quick tier"
        )
    return args


def at_least_one(text: str) -> int:
    """A number of jobs to run at once, which is one or more."""
    number = int(text)
    if number < 1:
        raise argparse.ArgumentTypeError(f"{number} is fewer than one")
    return number


def parse_run(arguments: list[str]) -> argparse.Namespace:
    """What was asked of a run in CI."""
    parser = argparse.ArgumentParser(
        prog="tools/ci.py run",
        description="Run the steps of the jobs named, in order, as CI does.",
    )
    parser.add_argument(
        "jobs",
        nargs="+",
        choices=list(JOBS_BY_NAME),
        metavar="job",
        help="the jobs to run, in order: %(choices)s",
    )
    return parser.parse_args(arguments)


def list_jobs(docker: bool) -> None:
    """Print each job: what it is for, what it needs, and how to run it here.

    A job that cannot run here says why. `docker` says whether the jobs in
    Docker were asked for.
    """
    indent = " " * (NAME_WIDTH + 2)
    settled = settle(JOBS, docker)
    for job in JOBS:
        print(f"{job.name:<{NAME_WIDTH}}  {job.blurb}")
        workflows = " and ".join(t.value for t in Tier if t in job.tiers)
        print(f"{indent}runs in {workflows}")
        if job.needs:
            print(f"{indent}needs {', '.join(job.needs)}")
        outcome = settled.get(job.name)
        if outcome:
            print(f"{indent}{outcome.verdict.mark()} {outcome.describe()}")
        print(f"{indent}{command_for(job)}")


def run_for_ci(names: list[str]) -> int:
    """Run the jobs named, one step after another, and stop at a failure."""
    for name in names:
        job = JOBS_BY_NAME[name]
        print(header(job))
        prepare(job)
        for step in job.steps_for(Mode.CI):
            if not run_in_ci(f"{name} ▸ {step.label}", step):
                return 1
    return 0


def empty(directories: tuple[str, ...]) -> None:
    """Throw away what is in each directory, the directory too."""
    for directory in directories:
        shutil.rmtree(REPO / directory, ignore_errors=True)


def prepare(job: Job) -> None:
    """Leave the directories a job asks for as it asks for them."""
    empty(job.fresh)
    for directory in job.made:
        (REPO / directory).mkdir(parents=True, exist_ok=True)


class Verdict(enum.Enum):
    """How a job ended, as the mark it is shown with."""

    PASSED = "✅"
    FAILED = "❌"
    SKIPPED = "⏭"
    # A run that was stopped never gives one of its jobs an end.
    INTERRUPTED = "🛑"

    def mark(self) -> str:
        """The mark, padded to the width the others take in a terminal."""
        return "⏭ " if self is Verdict.SKIPPED else self.value


@dataclass(frozen=True)
class Outcome:
    """How a job ended, and what to say of it."""

    verdict: Verdict
    # How long it ran, or None if it failed before it started.
    seconds: float | None = 0
    # The step it failed at, or why it was skipped.
    detail: str = ""

    def describe(self) -> str:
        """What a person is told: 41s, 3m02s at build, or why it skipped."""
        if self.verdict is Verdict.PASSED:
            return duration(self.seconds or 0)
        if self.verdict is Verdict.FAILED:
            at = f"at {self.detail}"
            return (
                at if self.seconds is None else f"{duration(self.seconds)} {at}"
            )
        return self.detail


INTERRUPTED = Outcome(Verdict.INTERRUPTED, detail="interrupted")

COLORS: dict[Verdict | None, str] = {
    Verdict.PASSED: "\x1b[32m",
    Verdict.FAILED: "\x1b[31m",
}
RESET = "\x1b[0m"


@dataclass(frozen=True)
class StepEnded:
    """A step of a job running here has ended."""

    job: str
    label: str
    passed: bool
    seconds: float
    log: Path


@dataclass(frozen=True)
class JobEnded:
    """A job running here has ended."""

    job: str
    outcome: Outcome


def run_here(
    names: list[str], tier: Tier, parallel: int, docker: bool, clean: bool
) -> int:
    """Run the jobs named, or every job of a tier, here.

    Returns the exit status. `docker` says whether the jobs in Docker were
    asked for, and `clean` whether to drop the patched dependencies
    whatever the patches are.
    """
    started = time.monotonic()
    jobs = (
        [job for job in JOBS if job.name in names]
        if names
        else [job for job in JOBS if tier in job.tiers]
    )
    LOGS.mkdir(parents=True, exist_ok=True)
    drop_stale_dependencies(clean)
    # A job in Docker that was named was asked for.
    settled = settle(jobs, docker or bool(names))
    return Run(jobs, parallel, settled, started).go()


@dataclass(frozen=True)
class Checked:
    """How tools/doctor.py found an area of this machine."""

    title: str
    # Whether the jobs that need it are skipped without it, not failed.
    optional: bool
    problems: list[str]
    # What to do about them.
    fix: list[str]


def settle(jobs: list[Job], docker: bool) -> dict[str, Outcome]:
    """How each job that will not run ends, before any starts, by its name.

    A job is skipped for a reason why_skipped gives. Of the rest, a job
    fails if this machine is missing what it needs, and is skipped if what
    is missing is optional, as tools/doctor.py says when it is asked, once,
    about the areas of every job left. `docker` says whether the jobs in
    Docker were asked for.
    """
    settled = {
        job.name: Outcome(Verdict.SKIPPED, detail=reason)
        for job in jobs
        if (reason := why_skipped(job, docker))
    }
    left = [job for job in jobs if job.name not in settled]
    areas = list(
        dict.fromkeys(area for job in left for area in job.every_area())
    )
    if not areas:
        return settled
    checked = ask_the_doctor(areas)
    for job in left:
        missing = [
            checked[area] for area in job.every_area() if checked[area].problems
        ]
        required = [each for each in missing if not each.optional]
        if required:
            detail = f"the check of {required[0].title}"
            settled[job.name] = Outcome(Verdict.FAILED, None, detail)
        elif missing:
            detail = f"needs {missing[0].title}: {missing[0].problems[0]}"
            settled[job.name] = Outcome(Verdict.SKIPPED, detail=detail)
    return settled


def ask_the_doctor(areas: list[str]) -> dict[str, Checked]:
    """Ask tools/doctor.py how this machine is in each area, and say so."""
    answer = subprocess.run(
        [sys.executable, str(REPO / "tools" / "doctor.py"), "--json", *areas],
        cwd=REPO,
        # What goes wrong with the doctor itself is said on its error
        # output, which goes to the terminal.
        stdout=subprocess.PIPE,
        text=True,
    )
    checked = {
        area["name"]: Checked(
            area["title"], area["optional"], area["problems"], area["fix"]
        )
        for area in json.loads(answer.stdout)["areas"]
    }
    wrong = [each for each in checked.values() if each.problems]
    if not wrong:
        print("🩺 this machine has what the jobs need")
    else:
        print("🩺 this machine is missing what some jobs need")
    for each in wrong:
        mark = "⚠️" if each.optional else Verdict.FAILED.mark()
        print(f"   {mark} {each.title}: {'; '.join(each.problems)}")
        for fix in each.fix:
            print(f"        {fix}")
    return checked


def drop_stale_dependencies(clean: bool) -> None:
    """Drop a tree's patched dependencies when the patches have changed.

    git apply does not apply a patch twice, so a build tree whose
    dependencies an older set of patches was applied to stops at configure
    with "patch does not apply". Each tree keeps a hash of what the patches
    are made from, beside its dependencies, and when the patches' hash is
    not its own, or it has none, or `clean` asks, each of its patched
    dependencies is dropped, to be fetched and patched again. What is not
    patched is slow to build, and is kept.

    💡 The record is the tree's own, and not one for all of them: a run in
    the container sees its own trees where QBox's are, which
    tools/devcontainer.py keeps apart from the host's, and the host's are
    left as they were.
    """
    current = patches_hash()
    patched = patched_dependencies()
    # socpuppet's trees, as the presets name them, and QBox's own patch to
    # rpclib in tools/build_qbox.py's tree, which CPM applies with `git am`
    # and which applied twice stops the configure. libqemu is left alone:
    # it is the slow one, and tools/build_qbox.py keeps its own patches.
    trees = {
        REPO / "build" / "dev": patched,
        REPO / "build" / "qbox-dev": patched,
        REPO / "build" / "linux": patched,
        # The linux preset's tree of each Ubuntu's container, which is
        # build/linux in there (tools/devcontainer.py): those of the Ubuntus
        # the devcontainer jobs build on, and any other there is.
        **dict.fromkeys(
            {
                *(REPO / container_tree(version) for version in UBUNTUS),
                *(REPO / "build" / "container").glob("ubuntu-*/linux"),
            },
            patched,
        ),
        REPO / "build" / "qbox" / "build": {"rpclib"},
    }
    for tree, names in trees.items():
        deps = tree / "_deps"
        record = deps / ".socpuppet-patches"
        same = record.exists() and record.read_text().strip() == current
        if same and not clean:
            continue
        if any((deps / f"{name}-src").exists() for name in names):
            why = (
                "--clean asks"
                if same
                else "the patches have changed since they were applied, or "
                "there is no record of them"
            )
            print(
                f"🧹 dropping {tree.relative_to(REPO)}'s patched "
                f"dependencies, as {why}"
            )
        for name in names:
            for part in ("src", "build", "subbuild"):
                shutil.rmtree(deps / f"{name}-{part}", ignore_errors=True)
        # A tree not made yet is recorded now, so that it is current once
        # it is configured.
        deps.mkdir(parents=True, exist_ok=True)
        record.write_text(current + "\n")


def patches_hash() -> str:
    """A hash of what the patches are, and of what applies them.

    The first two are what CI's cache of build/dev/_deps is keyed on, so
    that a change to Dependencies.cmake, a comment even, drops here what
    CI fetches again.
    """
    digest = hashlib.sha256()
    for path in (
        REPO / "cmake" / "Dependencies.cmake",
        *sorted((REPO / "cmake" / "patches").glob("*")),
        REPO / "tools" / "build_qbox.py",
    ):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def patched_dependencies() -> set[str]:
    """The dependencies cmake/Dependencies.cmake patches.

    Each is the FetchContent_Declare that a PATCH_COMMAND sits in, by the
    name FetchContent gives its directories, which is lowercased.
    """
    patched = set()
    name = ""
    text = (REPO / "cmake" / "Dependencies.cmake").read_text()
    for line in text.splitlines():
        declared = re.search(r"FetchContent_Declare\(\s*([\w-]+)", line)
        if declared:
            name = declared[1].lower()
        if "PATCH_COMMAND" in line:
            patched.add(name)
    return patched


def why_skipped(job: Job, docker: bool) -> str | None:
    """Why a run here skips a job, or None if it runs it.

    A job is skipped when it runs in Docker and that was not asked for.
    `docker` says whether the jobs in Docker were asked for. Whether this
    machine has what a job needs is tools/doctor.py's to say.
    """
    if job.docker and not docker:
        return "runs in Docker, which --docker asks for"
    return None


class Run:
    """A run of jobs on this machine, each step's output in a log.

    Up to `parallel` jobs run at once, each in a thread of its own, and a
    job starts once the jobs it needs have passed and nothing it uses is in
    use. A job higher in the table starts before one lower down. Everything
    is printed from here, as the threads report what they did.
    """

    def __init__(
        self,
        jobs: list[Job],
        parallel: int,
        settled: dict[str, Outcome],
        started: float,
    ) -> None:
        self.jobs = jobs
        # When the run started, by time.monotonic(), before the check of
        # this machine.
        self.started = started
        # How each job that will not run ends, which is settled before any
        # starts.
        self.settled = settled
        self.named = {job.name for job in jobs}
        self.parallel = parallel
        # What only this thread reads and writes.
        self.outcomes: dict[str, Outcome] = {}
        self.running: set[str] = set()
        self.held: set[str] = set()
        # What the threads tell this one.
        self.events: queue.Queue[StepEnded | JobEnded] = queue.Queue()
        # The step each job is running, which the threads write and this
        # one reads to stop them, and whether they are to stop.
        self.lock = threading.Lock()
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.stopping = threading.Event()

    def go(self) -> int:
        """Run every job, then sum up. Returns the exit status."""
        jobs = f"{len(self.jobs)} job{'s' if len(self.jobs) != 1 else ''}"
        print(f"🧦 {jobs}, {self.parallel} at a time, logs in build/ci/")
        try:
            while True:
                self.start_what_can_start()
                if not self.running:
                    break
                event = self.events.get()
                if isinstance(event, StepEnded):
                    report_step(event)
                else:
                    self.running.remove(event.job)
                    self.held.difference_update(JOBS_BY_NAME[event.job].uses)
                    self.end(event.job, event.outcome)
        except KeyboardInterrupt:
            self.stop()
            self.summarize()
            return 130
        self.restore_dev()
        self.summarize()
        failed = any(
            outcome.verdict is Verdict.FAILED
            for outcome in self.outcomes.values()
        )
        return 1 if failed else 0

    def start_what_can_start(self) -> None:
        """Start each job that is ready, and skip each that never will be."""
        for job in self.jobs:
            if job.name in self.outcomes or job.name in self.running:
                continue
            unmet = next(
                (
                    need
                    for need in job.needs
                    if need in self.outcomes
                    and self.outcomes[need].verdict is not Verdict.PASSED
                ),
                None,
            )
            if job.name in self.settled:
                self.end(job.name, self.settled[job.name])
            elif unmet:
                how = (
                    "was skipped"
                    if self.outcomes[unmet].verdict is Verdict.SKIPPED
                    else "failed"
                )
                reason = f"needs {unmet}, which {how}"
                self.end(job.name, Outcome(Verdict.SKIPPED, detail=reason))
            elif self.ready(job):
                self.running.add(job.name)
                self.held.update(job.uses)
                self.say(job.name, "starting")
                threading.Thread(
                    target=self.work, args=(job,), daemon=True
                ).start()

    def ready(self, job: Job) -> bool:
        """Whether a job may start now.

        The jobs it needs that were named have passed, there is room for
        one more, and nothing it uses is in use.
        """
        return (
            all(
                need not in self.named or need in self.outcomes
                for need in job.needs
            )
            and len(self.running) < self.parallel
            and not self.held & set(job.uses)
        )

    def work(self, job: Job) -> None:
        """Run a job's steps, each with its output in a log, until one fails.

        This is a thread of its own. It says what happened on self.events:
        each step's end, then the job's.
        """
        started = time.monotonic()
        prepare(job)
        for step in job.steps_for(Mode.HERE):
            log = LOGS / f"{job.name}-{step.label}.log"
            step_started = time.monotonic()
            passed = self.run_step(job, step, log)
            if passed is None:
                return
            took = time.monotonic() - step_started
            ended = StepEnded(job.name, step.label, passed, took, log)
            self.events.put(ended)
            if not passed:
                took = time.monotonic() - started
                outcome = Outcome(Verdict.FAILED, took, step.label)
                self.events.put(JobEnded(job.name, outcome))
                return
        took = time.monotonic() - started
        self.events.put(JobEnded(job.name, Outcome(Verdict.PASSED, took)))

    def run_step(self, job: Job, step: Step, log: Path) -> bool | None:
        """Run one step with its output in a log. Returns whether it passed.

        Returns None if the run is stopping, and the step was not started.
        """
        with log.open("w") as output:
            try:
                command = step.command()
            except NoMatch as no_match:
                output.write(f"{no_match}\n")
                return False
            with self.lock:
                if self.stopping.is_set():
                    return None
                process = subprocess.Popen(
                    command,
                    cwd=REPO,
                    env={**os.environ, **step.env},
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                self.processes[job.name] = process
        return process.wait() == 0

    def restore_dev(self) -> None:
        """Configure build/dev for dev again, if a job configured it otherwise.

        The presets other than qbox share build/dev, which holds whichever
        was configured last.
        """
        if not any(job.reconfigures_dev for job in self.jobs):
            return
        print("🔧 configuring build/dev for dev again")
        log = LOGS / "restore-dev.log"
        with log.open("w") as output:
            restored = subprocess.run(
                CONFIGURE_DEV,
                cwd=REPO,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        if restored.returncode != 0:
            print(f"⚠️  build/dev was not configured for dev again: see {log}")

    def stop(self) -> None:
        """Stop the steps that are running, and start no more.

        Each step is in a process group of its own, which the terminal's
        Ctrl-C does not reach, so it is stopped from here.
        """
        with self.lock:
            self.stopping.set()
            stopped = [self.processes.get(name) for name in self.running]
        for process in stopped:
            if process:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)

    def end(self, name: str, outcome: Outcome) -> None:
        """Record how a job ended, and say so."""
        self.outcomes[name] = outcome
        self.say(name, outcome.describe(), outcome.verdict)

    def say(self, name: str, text: str, verdict: Verdict | None = None) -> None:
        """Print what happened to a job, and how far the whole run has got.

        A job with no verdict has just started.
        """
        verdicts = [outcome.verdict for outcome in self.outcomes.values()]
        waiting = len(self.jobs) - len(self.outcomes) - len(self.running)
        counts = [
            *(
                f"{verdicts.count(kind):2} {kind.mark()}"
                for kind in (Verdict.PASSED, Verdict.FAILED, Verdict.SKIPPED)
            ),
            f"{len(self.running):2} 🏃",
            f"{waiting:2} ⏳",
        ]
        tally = " ".join(counts)
        mark = verdict.mark() if verdict else "🚀"
        line = paint(f"{mark} {name:<{NAME_WIDTH}}  {text:<40}", verdict)
        print(f"{line} [ {tally} ]")

    def summarize(self) -> None:
        """Say how long the run took, and how each job ended, in order."""
        took = duration(time.monotonic() - self.started)
        print(f"\n🧦 Summary, {took} in all")
        for job in self.jobs:
            outcome = self.outcomes.get(job.name, INTERRUPTED)
            mark = outcome.verdict.mark()
            if outcome.verdict in (Verdict.PASSED, Verdict.FAILED):
                line = f"{mark} {job.name} ({outcome.describe()})"
            else:
                line = f"{mark} {job.name}: {outcome.describe()}"
            print(f"   {paint(line, outcome.verdict)}")


def report_step(step: StepEnded) -> None:
    """Say how a step ended, and for one that failed, how its output ends."""
    title = f"{step.job} ▸ {step.label}"
    verdict = Verdict.PASSED if step.passed else Verdict.FAILED
    ended = paint(f"{verdict.mark()} {duration(step.seconds)}", verdict)
    print(f"   {title:<40} {ended}")
    if not step.passed:
        print(f"     output: {step.log.relative_to(REPO)}")
        for line in step.log.read_text(errors="replace").splitlines()[-15:]:
            print(f"     | {line}")


def paint(text: str, verdict: Verdict | None) -> str:
    """Color what a verdict says, for a person at a terminal.

    Green for a pass and red for a failure, unless the output is not a
    terminal or the person set NO_COLOR.
    """
    color = COLORS.get(verdict)
    if not color or not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{color}{text}{RESET}"


def header(job: Job) -> str:
    """What a job's log opens with: what it is, and how to run it here.

    A job that failed in CI is run again on a developer's machine with the
    command it names, set up as docs/setup.md says.
    """
    return (
        f"🧦 {job.name} — {job.blurb}\n"
        f"   To run this on your machine:  {command_for(job)}"
    )


def command_for(job: Job) -> str:
    """The command that runs a job here, with the jobs it needs first."""
    names = [other.name for other in JOBS if other.name in needed_by(job)]
    return " ".join(["uv run python tools/ci.py", *names, job.name])


def needed_by(job: Job) -> set[str]:
    """The jobs a job needs, and the jobs they need, all the way down."""
    needed: set[str] = set()
    waiting = list(job.needs)
    while waiting:
        name = waiting.pop()
        if name not in needed:
            needed.add(name)
            waiting.extend(JOBS_BY_NAME[name].needs)
    return needed


def run_in_ci(title: str, step: Step) -> bool:
    """Run one step with its output going straight to CI's log.

    Returns True if it passed. On GitHub Actions the output is folded into
    a group named after the step, which the job's page opens on a click.
    """
    try:
        command = step.command()
    except NoMatch as no_match:
        print(f"❌ {title}: {no_match}")
        return False
    folded = os.environ.get("GITHUB_ACTIONS") == "true"
    print(f"::group::{title}" if folded else f"▶ {title}")
    started = time.monotonic()
    finished = subprocess.run(command, cwd=REPO, env={**os.environ, **step.env})
    if folded:
        print("::endgroup::")
    took = duration(time.monotonic() - started)
    if finished.returncode != 0:
        print(f"❌ {title} failed after {took} (exit {finished.returncode})")
        return False
    print(f"✅ {title} {took}")
    return True


def duration(seconds: float) -> str:
    """A time as a person reads it: 41s, or 3m02s."""
    whole = round(seconds)
    return f"{whole}s" if whole < 60 else f"{whole // 60}m{whole % 60:02d}s"


if __name__ == "__main__":
    sys.exit(main())
