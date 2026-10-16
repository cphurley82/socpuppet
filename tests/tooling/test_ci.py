"""tools/ci.py, which runs CI's jobs: every one on this machine, or one in CI.

The runner is run for real in a throwaway copy of the repository, with
stand-ins for uv and the scripts the jobs call. Each stand-in writes the
command it was given to a log, so the tests can say what the runner ran, and
in what order, without building anything.
"""

import importlib.util
import itertools
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "tools" / "ci.py"

# A program that logs its command line, says it on its output, then says
# as many lines more as LINES asks, and exits with the status the test asked
# for: FAIL_ON names a word, and a command that holds it fails (a program
# is named by its file's name). It takes as many seconds as SLOW says. Each
# command is also written to the log's .json, with socpuppet's variables and
# when it started and ended, and its process id to the log's .pids when it
# starts.
STAND_IN = """\
import json, os, sys, time
command = " ".join([os.path.basename(sys.argv[0]), *sys.argv[1:]])
started = time.time()
with open(os.environ["LOG"], "a") as log:
    log.write(command + "\\n")
with open(os.environ["LOG"] + ".pids", "a") as log:
    log.write(f"{os.getpid()}\\n")
print("spam spam spam " + command)
for line in range(1, int(os.environ.get("LINES", "0")) + 1):
    print(f"eggs {line}")
time.sleep(float(os.environ.get("SLOW", "0")))
with open(os.environ["LOG"] + ".json", "a") as log:
    log.write(json.dumps({
        "command": command,
        "env": {k: v for k, v in os.environ.items()
                if k.startswith("SOCPUPPET_")},
        "start": started,
        "end": time.time(),
    }) + "\\n")
sys.exit(1 if os.environ.get("FAIL_ON", "@") in command.split() else 0)
"""

# The scripts in the repository that the jobs call.
SCRIPTS = ("firmware/build.sh", "tools/devcontainer.sh")

# What the runner is told by the environment it runs in, which the tests
# decide for themselves.
DECIDED_BY_THE_TEST = ("GITHUB_ACTIONS",)


def load_runner():
    """tools/ci.py as a module, for what its table says."""
    spec = importlib.util.spec_from_file_location("ci", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


JOBS = load_runner().JOBS
JOBS_BY_NAME = {job.name: job for job in JOBS}
# The jobs that run here with no option given.
JOBS_HERE = [job for job in JOBS if not job.docker]


@pytest.fixture
def ci(tmp_path):
    """Run the runner in a copy of the repo; returns run(*args, **env).

    run returns the finished process and the commands the stand-ins were
    given, in order. run.root is the copy, run.start(*args, **env) starts
    the runner and returns the process, run.lines() are the commands so far,
    run.commands() the commands that ended, with their variables and times,
    run.command(name) the one of them named, and run.pids() the process ids
    of the commands that started.
    """
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    shutil.copy(RUNNER, root / "tools" / "ci.py")
    for script in SCRIPTS:
        write_stand_in(root / script)
    bin_directory = tmp_path / "bin"
    write_stand_in(bin_directory / "uv")
    log = tmp_path / "log"

    def start(*args, **env):
        return subprocess.Popen(
            [sys.executable, str(root / "tools" / "ci.py"), *args],
            cwd=root,
            env={
                **{
                    name: value
                    for name, value in os.environ.items()
                    if not name.startswith("SOCPUPPET_")
                    and name not in DECIDED_BY_THE_TEST
                },
                "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
                "LOG": str(log),
                **env,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    def run(*args, **env):
        process = start(*args, **env)
        stdout, _ = process.communicate()
        result = subprocess.CompletedProcess(
            process.args, process.returncode, stdout
        )
        return result, lines()

    def lines():
        return log.read_text().splitlines() if log.exists() else []

    def pids():
        return [int(line) for line in Path(f"{log}.pids").read_text().split()]

    def commands():
        path = Path(f"{log}.json")
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def command(name):
        return next(c for c in commands() if c["command"] == name)

    run.root = root
    run.start = start
    run.lines = lines
    run.commands = commands
    run.pids = pids
    run.command = command
    return run


def test_run_lint_runs_the_linters_and_nothing_else(ci):
    result, lines = ci("run", "lint")

    assert result.returncode == 0, result.stdout
    assert lines == ["uv run python tools/lint.py"]


def test_run_test_configures_builds_and_tests_the_dev_tree_in_that_order(ci):
    result, lines = ci("run", "test")

    assert result.returncode == 0, result.stdout
    assert lines == [
        "uv run cmake --preset dev",
        "uv run cmake --build --preset dev",
        "uv run ctest --preset dev",
    ]


def test_run_test_requires_the_firmware_of_ctest_and_not_of_the_build(ci):
    ci("run", "test")

    required = {
        command["command"]: "SOCPUPPET_REQUIRE_FIRMWARE" in command["env"]
        for command in ci.commands()
    }
    assert required == {
        "uv run cmake --preset dev": False,
        "uv run cmake --build --preset dev": False,
        "uv run ctest --preset dev": True,
    }


def test_run_stops_a_job_at_the_step_that_fails_and_says_which(ci):
    result, lines = ci("run", "test", FAIL_ON="--build")

    assert result.returncode == 1
    assert lines == [
        "uv run cmake --preset dev",
        "uv run cmake --build --preset dev",
    ]
    assert "❌ test ▸ build" in result.stdout


def test_run_of_two_jobs_does_not_start_the_second_when_the_first_fails(ci):
    _, lines = ci("run", "lint", "test", FAIL_ON="tools/lint.py")

    assert lines == ["uv run python tools/lint.py"]


def test_an_unknown_job_is_refused_and_the_usage_names_every_job(ci):
    result, lines = ci("run", "spam")

    assert result.returncode == 2
    for job in JOBS:
        assert job.name in result.stdout
    assert lines == []


def test_run_shows_each_steps_own_output_and_leaves_no_file_behind(ci):
    before = files_in(ci.root)

    result, _ = ci("run", "test")

    assert "spam spam spam uv run cmake --build --preset dev" in result.stdout
    assert files_in(ci.root) == before


def test_run_in_github_actions_folds_each_steps_output_into_a_group(ci):
    result, _ = ci("run", "test", GITHUB_ACTIONS="true")

    assert groups(result.stdout) == {
        "test ▸ configure": ["spam spam spam uv run cmake --preset dev"],
        "test ▸ build": ["spam spam spam uv run cmake --build --preset dev"],
        "test ▸ ctest": ["spam spam spam uv run ctest --preset dev"],
    }


def test_run_opens_with_the_command_that_runs_the_job_and_its_needs_here(ci):
    result, _ = ci("run", "test")

    assert command_to_run_here(result.stdout) == (
        "uv run python tools/ci.py firmware test"
    )


@pytest.mark.parametrize("job", JOBS, ids=lambda job: job.name)
def test_the_command_to_run_a_job_here_names_what_it_needs_before_it(ci, job):
    result, _ = ci("run", job.name)

    named = command_to_run_here(result.stdout).split()
    for need in job.needs:
        assert named.index(need) < named.index(job.name)


def test_run_of_a_job_in_docker_says_to_run_it_here_with_docker(ci):
    docker_job = next(job for job in JOBS if job.docker)

    result, _ = ci("run", docker_job.name)

    assert "--docker" in command_to_run_here(result.stdout).split()


def test_with_no_job_named_every_job_that_can_run_here_runs_and_passes(ci):
    result, _ = ci()

    assert result.returncode == 0, result.stdout
    assert verdicts(result.stdout) == {
        job.name: "✅" for job in JOBS if not job.docker
    } | {job.name: "⏭" for job in JOBS if job.docker}


def test_a_failed_step_shows_where_its_output_is_and_how_it_ends(ci):
    result, _ = ci("lint", FAIL_ON="tools/lint.py", LINES="20")

    assert result.returncode == 1
    shown = next(
        line.split("output:", 1)[1].strip()
        for line in result.stdout.splitlines()
        if "output:" in line
    )
    log = (ci.root / shown).read_text()
    assert "spam spam spam uv run python tools/lint.py" in log
    # The last fifteen lines of the twenty it said, and none before them.
    ends = [
        line.split()[-1]
        for line in result.stdout.splitlines()
        if "eggs" in line
    ]
    assert ends == [str(line) for line in range(6, 21)]


def test_a_failed_job_does_not_stop_the_jobs_that_do_not_need_it(ci):
    result, _ = ci("lint", "firmware", FAIL_ON="tools/lint.py")

    assert result.returncode == 1
    assert verdicts(result.stdout) == {"lint": "❌", "firmware": "✅"}


def test_a_job_whose_need_failed_is_skipped_and_the_summary_says_why(ci):
    result, lines = ci("firmware", "test", FAIL_ON="build.sh")

    assert result.returncode == 1
    assert summary_of(result.stdout, "test") == (
        "⏭  test: needs firmware, which failed"
    )
    assert not set(commands_of("test")) & set(lines)


def test_a_job_named_alone_runs_without_the_jobs_it_needs(ci):
    result, lines = ci("test")

    assert result.returncode == 0, result.stdout
    assert verdicts(result.stdout) == {"test": "✅"}
    assert not set(commands_of("firmware")) & set(lines)


def test_jobs_named_in_any_order_run_after_the_jobs_they_need(ci):
    _, lines = ci("test", "firmware")

    last_of_firmware = lines.index(commands_of("firmware")[-1])
    assert last_of_firmware < lines.index(commands_of("test")[0])


# SLOW holds each command open for half a second, far longer than a process
# takes to start, so that two jobs run together are seen to overlap.


def test_two_at_a_time_runs_jobs_that_share_nothing_together(ci):
    first, second = next(
        (a, b)
        for a, b in itertools.combinations(JOBS_HERE, 2)
        if independent(a, b)
        and not set(commands_of(a.name)) & set(commands_of(b.name))
    )

    result, _ = ci("-j", "2", first.name, second.name, SLOW="0.5")

    assert result.returncode == 0, result.stdout
    a, b = (
        [c for c in ci.commands() if c["command"] in commands_of(job.name)]
        for job in (first, second)
    )
    assert a[0]["start"] < b[-1]["end"]
    assert b[0]["start"] < a[-1]["end"]


def test_two_at_a_time_runs_jobs_that_share_a_build_tree_one_after_another(
    ci,
):
    first, second = next(
        (a, b)
        for a, b in itertools.combinations(JOBS_HERE, 2)
        if independent(a, b) and set(a.uses) & set(b.uses)
    )

    result, _ = ci("-j", "2", first.name, second.name, SLOW="0.5")

    assert result.returncode == 0, result.stdout
    # No command overlaps another, of its own job or of the other.
    commands = sorted(ci.commands(), key=lambda command: command["start"])
    for before, after in itertools.pairwise(commands):
        assert after["start"] >= before["end"]


def test_one_at_a_time_runs_the_jobs_in_the_tables_order(ci):
    names = ["tidy", "firmware", "lint"]

    _, lines = ci("-j", "1", *names)

    started = sorted(names, key=lambda name: lines.index(commands_of(name)[0]))
    assert started == [job.name for job in JOBS if job.name in names]


def test_a_run_opens_with_how_many_jobs_and_how_many_at_a_time(ci):
    result, _ = ci("-j", "2", "lint", "firmware", "test")

    assert result.stdout.startswith("🧦 3 jobs, 2 at a time")


def test_a_run_says_at_each_job_how_far_the_whole_run_has_got(ci):
    result, _ = ci("-j", "2", "lint", "firmware", "test", FAIL_ON="build.sh")

    events = {
        (line.split()[0], line.split()[1]): tally(line)
        for line in result.stdout.splitlines()
        if line.endswith("]")
    }
    assert set(events) == {
        ("🚀", "lint"),
        ("✅", "lint"),
        ("🚀", "firmware"),
        ("❌", "firmware"),
        ("⏭", "test"),
    }
    for counts in events.values():
        assert sum(counts.values()) == 3
    assert events["❌", "firmware"]["❌"] == 1


def test_a_failed_job_says_which_step_it_failed_at(ci):
    first, step = JOBS_BY_NAME["test"].steps[:2]
    (word,) = set(step.argv) - set(first.argv)

    result, _ = ci("test", FAIL_ON=word)

    failed = next(
        line
        for line in result.stdout.splitlines()
        if line.startswith("❌ test")
    )
    assert f"at {step.label}" in failed


def test_the_list_shows_a_command_that_runs_each_job_here_and_runs_none(ci):
    result, lines = ci("--list")

    assert result.returncode == 0, result.stdout
    commands = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("uv run python tools/ci.py")
    ]
    assert [command.split()[-1] for command in commands] == [
        job.name for job in JOBS
    ]
    assert lines == []


def test_an_interrupted_run_stops_its_steps_and_says_how_far_it_got(ci):
    # Far longer than the test waits for the step to be stopped.
    run = ci.start("lint", SLOW="30")
    wait_for(lambda: ci.lines())

    run.send_signal(signal.SIGINT)
    stdout, _ = run.communicate(timeout=10)

    assert run.returncode == 130
    assert verdicts(stdout) == {"lint": "🛑"}
    (step,) = ci.pids()
    wait_for(lambda: not alive(step))


def write_stand_in(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{STAND_IN}")
    path.chmod(0o755)


def wait_for(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def files_in(directory):
    return sorted(directory.rglob("*"))


def command_to_run_here(output):
    """The command a job's log says runs it on a developer's machine."""
    marker = "To run this on your machine:"
    line = next(line for line in output.splitlines() if marker in line)
    return line.split(marker, 1)[1].strip()


def verdicts(output):
    """What the summary at the end of a run says of each job: ✅, ❌, ⏭ or 🛑."""
    summary = output.split("🧦 Summary", 1)[1]
    found = {}
    for line in summary.splitlines():
        if line.strip():
            verdict, name = line.split()[:2]
            found[name.rstrip(":")] = verdict
    return found


def needed_by(job):
    """The jobs a job needs, and the jobs they need, from the table."""
    needed = set(job.needs)
    for need in job.needs:
        needed |= needed_by(JOBS_BY_NAME[need])
    return needed


def independent(a, b):
    """Whether neither of two jobs needs the other."""
    return a.name not in needed_by(b) and b.name not in needed_by(a)


def commands_of(name):
    """A job's commands, as the stand-ins log them."""
    return [
        " ".join([Path(step.argv[0]).name, *step.argv[1:]])
        for step in JOBS_BY_NAME[name].steps
    ]


def summary_of(output, name):
    """The line the summary at the end of a run has for one job."""
    summary = output.split("🧦 Summary", 1)[1]
    return next(
        line.strip()
        for line in summary.splitlines()
        if line.split()[1:2] in ([name], [f"{name}:"])
    )


def tally(line):
    """The counts at the end of a line: {"✅": passed, "❌": failed, ...}."""
    words = line.rsplit("[", 1)[1].rstrip("]").split()
    return {
        emoji: int(count)
        for count, emoji in zip(words[::2], words[1::2], strict=True)
    }


def groups(output):
    """GitHub Actions' groups in an output: {title: the lines inside}."""
    found = {}
    inside = None
    for line in output.splitlines():
        if line.startswith("::group::"):
            inside = found.setdefault(line.removeprefix("::group::"), [])
        elif line == "::endgroup::":
            inside = None
        elif inside is not None:
            inside.append(line)
    return found
