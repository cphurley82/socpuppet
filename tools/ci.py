"""Run CI's jobs: every one that can run on this machine, or one in CI.

Usage:
  uv run python tools/ci.py run JOB [JOB ...]

`run` is what each job of .github/workflows/ci.yml calls: it runs the steps
of the jobs named, in order, and stops at the first that fails.
"""

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# The top of the repository, which every step is run from.
REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Step:
    """One command of a job, and what it is called in the job's output."""

    label: str
    argv: tuple[str, ...]
    # Variables set for this step alone.
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Job:
    """One of CI's jobs: its name, what it is for, and its steps."""

    name: str
    blurb: str
    steps: tuple[Step, ...]
    # The jobs whose output this one reads, which come before it in JOBS.
    needs: tuple[str, ...] = ()
    # Whether it runs in Docker.
    docker: bool = False


# Quick first: when two jobs could start, the one higher in the table does.
JOBS = [
    Job(
        "lint",
        "formatting and static checks on every file",
        steps=(Step("lint", ("uv", "run", "python", "tools/lint.py")),),
    ),
    Job(
        "firmware",
        "build the firmware images the tests boot",
        steps=(Step("build", ("firmware/build.sh",)),),
    ),
    Job(
        "test",
        "build the dev tree and run every test",
        needs=("firmware",),
        steps=(
            Step("configure", ("uv", "run", "cmake", "--preset", "dev")),
            Step("build", ("uv", "run", "cmake", "--build", "--preset", "dev")),
            Step(
                "ctest",
                ("uv", "run", "ctest", "--preset", "dev"),
                # A missing firmware image fails its boot test instead of
                # skipping it.
                env={"SOCPUPPET_REQUIRE_FIRMWARE": "1"},
            ),
        ),
    ),
    Job(
        "devcontainer",
        "build and test in the devcontainer's image, as Linux with GCC",
        # In build/linux, so that the host's own build/dev is left alone.
        steps=tuple(
            Step(label, ("tools/devcontainer.sh", "uv", "run", *argv))
            for label, argv in (
                ("configure", ("cmake", "--preset", "linux")),
                ("build", ("cmake", "--build", "--preset", "linux")),
                ("ctest", ("ctest", "--preset", "linux")),
            )
        ),
        docker=True,
    ),
]


JOBS_BY_NAME = {job.name: job for job in JOBS}


def main() -> int:
    """Run the jobs asked for. Returns the exit status."""
    # A line is shown as soon as it is printed, before a step's own output.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run jobs' steps, as CI does")
    run.add_argument(
        "jobs",
        nargs="+",
        choices=list(JOBS_BY_NAME),
        metavar="job",
        help="the jobs to run, in order: %(choices)s",
    )
    args = parser.parse_args()
    for name in args.jobs:
        job = JOBS_BY_NAME[name]
        print(header(job))
        for step in job.steps:
            if not run_in_ci(f"{name} ▸ {step.label}", step):
                return 1
    return 0


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
    docker = ["--docker"] if job.docker else []
    return " ".join(["uv run python tools/ci.py", *docker, *names, job.name])


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
    folded = os.environ.get("GITHUB_ACTIONS") == "true"
    print(f"::group::{title}" if folded else f"▶ {title}")
    started = time.monotonic()
    finished = subprocess.run(
        step.argv, cwd=REPO, env={**os.environ, **step.env}
    )
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
