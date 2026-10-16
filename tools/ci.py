"""Run CI's jobs: every one that can run on this machine, or one in CI.

Usage:
  uv run python tools/ci.py [-j N] [JOB ...]    every job that can run here,
                                                or the jobs named
  uv run python tools/ci.py --list              the jobs, and how to run each
  uv run python tools/ci.py run JOB [JOB ...]   in CI

Here, up to three jobs run at a time, quick ones first, and each step's
output is kept in build/ci/. A job named without the jobs it needs takes
what they make as made already.

`run` is what each job of .github/workflows/ci.yml calls: it runs the steps
of the jobs named, in order, with their output in CI's log, and stops at the
first that fails.
"""

import argparse
import contextlib
import enum
import os
import platform
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# The top of the repository, which every step is run from.
REPO = Path(__file__).resolve().parents[1]
# Where a run on this machine keeps each step's output.
LOGS = REPO / "build" / "ci"


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
    # What it builds in, or writes to, that no other job may use while it
    # runs here: a build tree, or the extension every tree puts in
    # python/socpuppet.
    uses: tuple[str, ...] = ()
    # Whether it runs in Docker.
    docker: bool = False
    # The one system it runs on (platform.system()'s name), if not every.
    only_on: str = ""
    # A path it runs for a change to, as CI's paths filter has it: here, it
    # runs when the path differs from main's.
    changed: str = ""


def tidy_steps(preset: str) -> tuple[Step, ...]:
    """Configure a tree, then run clang-tidy and the header check over it."""
    build = ("uv", "run", "cmake", "--build", "--preset", preset)
    return (
        Step("configure", ("uv", "run", "cmake", "--preset", preset)),
        Step("tidy", (*build, "--target", "tidy")),
        Step("check_headers", (*build, "--target", "check_headers")),
    )


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
        uses=("build/dev", "extension"),
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
        "tidy",
        "clang-tidy over our C++, and each header compiled on its own",
        steps=tidy_steps("dev"),
        uses=("build/dev",),
        # clang-tidy reads GCC's compile commands and standard library, so
        # it reads our code the way the Linux build compiles it.
        only_on="Linux",
    ),
    Job(
        "qbox-build",
        "build QBox, QEMU in SystemC, for the second hart",
        steps=(Step("build", ("uv", "run", "tools/build_qbox.sh")),),
        uses=("build/qbox",),
    ),
    Job(
        "qbox-tidy",
        "clang-tidy over the QBox adapter, which the dev tree leaves out",
        needs=("qbox-build",),
        steps=tidy_steps("qbox"),
        uses=("build/qbox-dev",),
        only_on="Linux",
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
        changed=".devcontainer",
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
    return run_here(args.jobs, args.parallel, args.docker)


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
        help="run only these (default: every one that can run here): "
        "%(choices)s",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="run the jobs in Docker too: "
        + ", ".join(job.name for job in JOBS if job.docker),
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
    return parser.parse_args(arguments)


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
    for job in JOBS:
        print(f"{job.name:<{NAME_WIDTH}}  {job.blurb}")
        if job.needs:
            print(f"{indent}needs {', '.join(job.needs)}")
        reason = why_skipped(job, docker)
        if reason:
            print(f"{indent}{Verdict.SKIPPED.mark()} {reason}")
        print(f"{indent}{command_for(job)}")


def run_for_ci(names: list[str]) -> int:
    """Run the jobs named, one step after another, and stop at a failure."""
    for name in names:
        job = JOBS_BY_NAME[name]
        print(header(job))
        for step in job.steps:
            if not run_in_ci(f"{name} ▸ {step.label}", step):
                return 1
    return 0


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
    seconds: float = 0
    # The step it failed at, or why it was skipped.
    detail: str = ""

    def describe(self) -> str:
        """What a person is told: 41s, 3m02s at build, or why it skipped."""
        took = duration(self.seconds)
        if self.verdict is Verdict.FAILED:
            return f"{took} at {self.detail}"
        if self.verdict is Verdict.PASSED:
            return took
        return self.detail


INTERRUPTED = Outcome(Verdict.INTERRUPTED, detail="interrupted")


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


def run_here(names: list[str], parallel: int, docker: bool) -> int:
    """Run the jobs named, or every one, here. Returns the exit status.

    `docker` says whether the jobs in Docker were asked for.
    """
    jobs = [job for job in JOBS if not names or job.name in names]
    LOGS.mkdir(parents=True, exist_ok=True)
    # A job in Docker that was named was asked for.
    return Run(jobs, parallel, docker or bool(names)).go()


def why_skipped(job: Job, docker: bool) -> str | None:
    """Why a run here skips a job, or None if it runs it.

    A job is skipped when this machine cannot run it, when it was not asked
    for, or when CI would skip it too. `docker` says whether the jobs in
    Docker were asked for. The cheaper questions are asked first.
    """
    if job.only_on and platform.system() != job.only_on:
        return f"runs on {job.only_on} alone"
    if job.docker and not docker:
        return "runs in Docker, which --docker asks for"
    if job.changed and not changed_from_main(job.changed):
        return f"{job.changed} is the same as main's, so CI skips it too"
    if job.docker and not shutil.which("docker"):
        return "needs Docker, which is not installed"
    if job.docker and not docker_answers():
        return (
            "needs Docker, and `docker info` fails: is the daemon running, "
            "and are you in the docker group?"
        )
    return None


def changed_from_main(path: str) -> bool:
    """Whether this branch has changed a path, committed or not, or added to it.

    As CI's paths filter does for a pull request, it compares with where
    the branch left main, so that what main has done since does not count.
    """
    base = git("merge-base", "main", "HEAD").stdout.strip()
    untracked = git("ls-files", "--others", "--exclude-standard", "--", path)
    differs = git("diff", "--quiet", base, "--", path)
    return bool(untracked.stdout) or differs.returncode != 0


def git(*args: str) -> subprocess.CompletedProcess[str]:
    """Ask git something about the repository."""
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True
    )


def docker_answers() -> bool:
    """Whether Docker's daemon is running, and lets this user in."""
    info = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return info.returncode == 0


class Run:
    """A run of jobs on this machine, each step's output in a log.

    Up to `parallel` jobs run at once, each in a thread of its own, and a
    job starts once the jobs it needs have passed and nothing it uses is in
    use. A job higher in the table starts before one lower down. Everything
    is printed from here, as the threads report what they did.
    """

    def __init__(self, jobs: list[Job], parallel: int, docker: bool) -> None:
        self.jobs = jobs
        # Whether a job is skipped is settled before any starts.
        self.skipped = {
            job.name: reason
            for job in jobs
            if (reason := why_skipped(job, docker))
        }
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
            if job.name in self.skipped:
                reason = self.skipped[job.name]
                self.end(job.name, Outcome(Verdict.SKIPPED, detail=reason))
            elif unmet:
                reason = f"needs {unmet}, which failed"
                self.end(job.name, Outcome(Verdict.SKIPPED, detail=reason))
            elif self.ready(job):
                self.running.add(job.name)
                self.held.update(job.uses)
                self.say("🚀", job.name, "starting")
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
        for step in job.steps:
            log = LOGS / f"{job.name}-{step.label}.log"
            step_started = time.monotonic()
            with log.open("w") as output, self.lock:
                if self.stopping.is_set():
                    return
                process = subprocess.Popen(
                    step.argv,
                    cwd=REPO,
                    env={**os.environ, **step.env},
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                self.processes[job.name] = process
            passed = process.wait() == 0
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
        self.say(outcome.verdict.mark(), name, outcome.describe())

    def say(self, mark: str, name: str, text: str) -> None:
        """Print what happened to a job, and how far the whole run has got."""
        verdicts = [outcome.verdict for outcome in self.outcomes.values()]
        waiting = len(self.jobs) - len(self.outcomes) - len(self.running)
        counts = [
            *(
                f"{verdicts.count(verdict):2} {verdict.mark()}"
                for verdict in (Verdict.PASSED, Verdict.FAILED, Verdict.SKIPPED)
            ),
            f"{len(self.running):2} 🏃",
            f"{waiting:2} ⏳",
        ]
        tally = " ".join(counts)
        print(f"{mark} {name:<{NAME_WIDTH}}  {text:<40} [ {tally} ]")

    def summarize(self) -> None:
        """Say how each job ended, in the table's order."""
        print("\n🧦 Summary")
        for job in self.jobs:
            outcome = self.outcomes.get(job.name, INTERRUPTED)
            mark = outcome.verdict.mark()
            if outcome.verdict in (Verdict.PASSED, Verdict.FAILED):
                print(f"   {mark} {job.name} ({outcome.describe()})")
            else:
                print(f"   {mark} {job.name}: {outcome.describe()}")


def report_step(step: StepEnded) -> None:
    """Say how a step ended, and for one that failed, how its output ends."""
    title = f"{step.job} ▸ {step.label}"
    verdict = "✅" if step.passed else "❌"
    print(f"   {title:<40} {verdict} {duration(step.seconds)}")
    if not step.passed:
        print(f"     output: {step.log.relative_to(REPO)}")
        for line in step.log.read_text(errors="replace").splitlines()[-15:]:
            print(f"     | {line}")


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
