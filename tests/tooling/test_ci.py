"""tools/ci.py, which runs CI's jobs: every one on this machine, or one in CI.

The runner is run for real in a throwaway copy of the repository, with
stand-ins for uv, the scripts the jobs call and tools/doctor.py. Each
stand-in writes the command it was given to a log, so the tests can say what
the runner ran, and in what order, without building anything.
"""

import importlib.util
import itertools
import json
import os
import platform
import pty
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "tools" / "ci.py"

# Three dependencies, two of them patched, one of those with a name that
# FetchContent lowercases.
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

# A program that logs its command line, says it on its output, then says
# as many lines more as LINES asks, and exits with the status the test asked
# for: FAIL_ON names a word, and a command that holds it fails (a program
# is named by its file's name). It takes as many seconds as SLOW says, and
# makes the files MAKES asks for: a JSON {word: [path, ...]}, where a
# command that holds the word makes the paths, empty. Each command is also
# written to the log's .json, with the variables whose names begin as
# RECORDED says and when it started and ended, and its process id to the log's .pids when it
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
for word, paths in json.loads(os.environ.get("MAKES", "{}")).items():
    if word in command.split():
        for path in paths:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
with open(os.environ["LOG"] + ".json", "a") as log:
    log.write(json.dumps({
        "command": command,
        "env": {k: v for k, v in os.environ.items()
                if k.startswith(tuple(os.environ["RECORDED"].split()))},
        "start": started,
        "end": time.time(),
    }) + "\\n")
sys.exit(1 if os.environ.get("FAIL_ON", "@") in command.split() else 0)
"""

# The doctor, which logs what it was asked to a log of its own, and says, as
# tools/doctor.py does in JSON, how each area asked about is: well, unless
# DOCTOR gives it a report, a JSON {area: {"problems": [...], ...}}.
DOCTOR = """\
import json, os, sys
asked = sys.argv[1:]
with open(os.environ["LOG"] + ".doctor", "a") as log:
    log.write(json.dumps(asked) + "\\n")
found = json.loads(os.environ.get("DOCTOR", "{}"))
print(json.dumps({"areas": [
    {"name": area, "title": f"the {area}", "optional": False,
     "problems": [], "fix": [], **found.get(area, {})}
    for area in asked if area != "--json"
]}))
"""

# The scripts in the repository that the jobs call.
SCRIPTS = (
    "tools/build_qbox.py",
    "tools/devcontainer.py",
    "tools/test_wheel.py",
)

# The Python the tools are pinned to, which the wheels are tested under.
PYTHON = "3.13"
TAG = "cp313"

SDIST = "build/wheelhouse/sdist/socpuppet-0.0.1.tar.gz"
OUR_WHEEL = f"build/wheelhouse/socpuppet-0.0.1-{TAG}-{TAG}-spam.whl"
# What the sdist and cibuildwheel stand-ins leave, to build one wheel here.
ONE_WHEEL = {"--sdist": [SDIST], "cibuildwheel": [OUR_WHEEL]}

# What a terminal is sent to color what follows.
GREEN, RED = "\x1b[32m", "\x1b[31m"

# What the runner is told by the environment it runs in, which the tests
# decide for themselves.
DECIDED_BY_THE_TEST = ("GITHUB_ACTIONS", "NO_COLOR")
# The variables a stand-in records: socpuppet's, and cibuildwheel's and
# ccache's. The tests' own environment has none of them.
RECORDED = ("SOCPUPPET_", "CIBW_", "CCACHE_")


def load(path):
    """A script of the repository's as a module, for what its tables say."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER_MODULE = load(RUNNER)
JOBS = RUNNER_MODULE.JOBS
JOBS_BY_NAME = {job.name: job for job in JOBS}
# The areas of this machine tools/doctor.py checks, by their names.
AREAS = {area.name: area for area in load(REPO / "tools" / "doctor.py").AREAS}
# The jobs that run here with no option given, and the jobs in Docker.
JOBS_HERE = [
    job
    for job in JOBS
    if not job.docker and job.only_on in ("", platform.system())
]
DOCKER_JOBS = [job.name for job in JOBS if job.docker]
LINUX_JOBS = [job.name for job in JOBS if job.only_on == "Linux"]
DEVCONTAINER = JOBS_BY_NAME["devcontainer"]


@pytest.fixture
def ci(tmp_path):
    """Run the runner in a copy of the repo; returns run(*args, **env).

    `makes` is what the stand-ins make (see STAND_IN's MAKES).

    run returns the finished process and the commands the stand-ins were
    given, in order. run.root is the copy, run.start(*args, **env) starts
    the runner and returns the process, run.on_a_terminal(*args, **env)
    runs it with its output going to a terminal and returns what that was
    sent, run.lines() are the commands so far,
    run.commands() the commands that ended, with their variables and times,
    run.command(name) the one of them named, run.command_with(word) the
    one that holds the word, run.pids() the process ids
    of the commands that started, and run.doctor_asked() the arguments the
    doctor was given each time it was asked.
    """
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    shutil.copy(RUNNER, root / "tools" / "ci.py")
    for script in SCRIPTS:
        write_stand_in(root / script)
    write_stand_in(root / "tools" / "doctor.py", DOCTOR)
    (root / "cmake" / "patches").mkdir(parents=True)
    (root / "cmake" / "Dependencies.cmake").write_text(DEPENDENCIES)
    (root / "cmake" / "patches" / "eggs-fix.patch").write_text("one\n")
    (root / ".python-version").write_text(f"{PYTHON}\n")
    git(root, "init", "-q", "-b", "main")
    commit_everything(root)
    bin_directory = tmp_path / "bin"
    write_stand_in(bin_directory / "uv")
    log = tmp_path / "log"

    def start(*args, stdout=subprocess.PIPE, makes=None, **env):
        if makes:
            env["MAKES"] = json.dumps(makes)
        return subprocess.Popen(
            [sys.executable, str(root / "tools" / "ci.py"), *args],
            cwd=root,
            env={
                **{
                    name: value
                    for name, value in os.environ.items()
                    if not name.startswith(RECORDED)
                    and name not in DECIDED_BY_THE_TEST
                },
                "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
                "LOG": str(log),
                "RECORDED": " ".join(RECORDED),
                **env,
            },
            stdout=stdout,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    def on_a_terminal(*args, **env):
        ours, theirs = pty.openpty()
        process = start(*args, stdout=theirs, **env)
        os.close(theirs)
        sent = b""
        while True:
            try:
                chunk = os.read(ours, 4096)
            except OSError:  # Linux reports the far end closing as an error.
                break
            if not chunk:
                break
            sent += chunk
        os.close(ours)
        process.wait()
        return sent.decode("utf-8")

    def run(*args, makes=None, **env):
        process = start(*args, makes=makes, **env)
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

    def command_with(word):
        (command,) = [c for c in commands() if word in c["command"].split()]
        return command

    def doctor_asked():
        path = Path(f"{log}.doctor")
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    run.root = root
    run.start = start
    run.on_a_terminal = on_a_terminal
    run.lines = lines
    run.commands = commands
    run.pids = pids
    run.command = command
    run.command_with = command_with
    run.doctor_asked = doctor_asked
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
        "uv run python tools/ci.py fetch-sdk fetch-llvm fetch-zephyr "
        "firmware-rom firmware-opensbi firmware-zephyr firmware-edk2 test"
    )


@pytest.mark.parametrize("job", JOBS, ids=lambda job: job.name)
def test_the_command_to_run_a_job_here_names_what_it_needs_before_it(ci, job):
    result, _ = ci("run", job.name)

    named = command_to_run_here(result.stdout).split()
    for need in job.needs:
        assert named.index(need) < named.index(job.name)


def test_with_no_job_named_every_job_that_can_run_here_runs_and_passes(ci):
    result, _ = ci(makes=ONE_WHEEL)

    assert result.returncode == 0, result.stdout
    assert verdicts(result.stdout) == {
        job.name: "✅" if job in JOBS_HERE else "⏭" for job in JOBS
    }


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
    result, _ = ci("lint", "firmware-rom", FAIL_ON="tools/lint.py")

    assert result.returncode == 1
    assert verdicts(result.stdout) == {"lint": "❌", "firmware-rom": "✅"}


def test_a_job_whose_need_failed_is_skipped_and_the_summary_says_why(ci):
    result, lines = ci("firmware-rom", "test", FAIL_ON="rom")

    assert result.returncode == 1
    assert summary_of(result.stdout, "test") == (
        "⏭  test: needs firmware-rom, which failed"
    )
    assert not set(commands_of("test")) & set(lines)


def test_a_job_named_alone_runs_without_the_jobs_it_needs(ci):
    result, lines = ci("test")

    assert result.returncode == 0, result.stdout
    assert verdicts(result.stdout) == {"test": "✅"}
    for need in JOBS_BY_NAME["test"].needs:
        assert not set(commands_of(need)) & set(lines)


def test_jobs_named_in_any_order_run_after_the_jobs_they_need(ci):
    _, lines = ci("test", "firmware-rom")

    last_of_firmware = lines.index(commands_of("firmware-rom")[-1])
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
    names = ["coverage", "firmware-rom", "lint"]

    _, lines = ci("-j", "1", *names)

    started = sorted(names, key=lambda name: lines.index(commands_of(name)[0]))
    assert started == [job.name for job in JOBS if job.name in names]


def test_a_run_says_how_many_jobs_it_has_and_how_many_at_a_time_before_any(
    ci,
):
    result, _ = ci("-j", "2", "lint", "firmware-rom", "test")

    output = result.stdout.splitlines()
    opening = next(i for i, line in enumerate(output) if line.startswith("🧦"))
    first_job = next(
        i for i, line in enumerate(output) if line.startswith("🚀")
    )
    assert output[opening].startswith("🧦 3 jobs, 2 at a time")
    assert opening < first_job


def test_a_run_says_at_each_job_how_far_the_whole_run_has_got(ci):
    result, _ = ci("-j", "2", "lint", "firmware-rom", "test", FAIL_ON="rom")

    events = {
        (line.split()[0], line.split()[1]): tally(line)
        for line in result.stdout.splitlines()
        if line.endswith("]")
    }
    assert set(events) == {
        ("🚀", "lint"),
        ("✅", "lint"),
        ("🚀", "firmware-rom"),
        ("❌", "firmware-rom"),
        ("⏭", "test"),
    }
    for counts in events.values():
        assert sum(counts.values()) == 3
    assert events["❌", "firmware-rom"]["❌"] == 1


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


def test_the_doctor_is_asked_once_about_every_area_the_jobs_need(ci):
    named = ("lint", "firmware-edk2", "test")

    ci(*named)

    (asked,) = ci.doctor_asked()
    assert "--json" in asked
    assert set(asked) - {"--json"} == {
        area for name in named for area in JOBS_BY_NAME[name].every_area()
    }


def test_jobs_that_need_nothing_of_this_machine_do_not_ask_the_doctor(ci):
    ci("lint")

    assert ci.doctor_asked() == []


def test_the_doctor_is_asked_about_docker_when_a_job_in_docker_will_run(ci):
    change_what_the_docker_jobs_run_for(ci.root)

    ci("devcontainer")
    ci("test")

    with_docker, without = ci.doctor_asked()
    assert "docker" in with_docker
    assert "docker" not in without


def test_a_job_this_machine_cannot_run_fails_before_any_starts_and_the_rest_run(
    ci,
):
    missing = {
        "edk2": {
            "problems": ["iasl is not installed"],
            "fix": ["sudo apt-get install -y acpica-tools"],
        }
    }

    result, lines = ci(
        "lint", "firmware-edk2", "firmware-rom", DOCTOR=json.dumps(missing)
    )

    assert result.returncode == 1
    assert verdicts(result.stdout) == {
        "lint": "✅",
        "firmware-edk2": "❌",
        "firmware-rom": "✅",
    }
    assert not set(commands_of("firmware-edk2")) & set(lines)
    said = before_any_job_started(result.stdout)
    assert "iasl is not installed" in said
    assert "sudo apt-get install -y acpica-tools" in said


def test_a_job_missing_something_optional_is_skipped_saying_what(ci):
    missing = {
        "qbox": {"optional": True, "problems": ["meson is not installed"]}
    }

    result, lines = ci("lint", "qbox-build", DOCTOR=json.dumps(missing))

    assert result.returncode == 0, result.stdout
    assert summary_of(result.stdout, "qbox-build") == (
        "⏭  qbox-build: needs the qbox: meson is not installed"
    )
    assert lines == commands_of("lint")
    said = before_any_job_started(result.stdout)
    assert "⚠️ the qbox: meson is not installed" in said


def test_a_job_whose_need_was_skipped_is_skipped_saying_so(ci):
    missing = {
        "qbox": {"optional": True, "problems": ["meson is not installed"]}
    }

    result, _ = ci("qbox-build", "qbox", DOCTOR=json.dumps(missing))

    assert summary_of(result.stdout, "qbox") == (
        "⏭  qbox: needs qbox-build, which was skipped"
    )


def test_the_summary_says_how_long_the_whole_run_took(ci):
    result, _ = ci("lint", SLOW="1")

    took = re.search(r"🧦 Summary, (\d+)s in all", result.stdout)
    ran = ci.commands()
    assert took
    assert int(took[1]) >= int(
        max(c["end"] for c in ran) - min(c["start"] for c in ran)
    )


def test_without_docker_asked_for_the_jobs_in_docker_are_skipped_saying_so(
    ci,
):
    result, _ = ci(makes=ONE_WHEEL)

    assert result.returncode == 0, result.stdout
    for name in DOCKER_JOBS:
        assert "--docker" in summary_of(result.stdout, name)


def test_with_docker_asked_for_and_missing_its_jobs_are_skipped_saying_why(
    ci,
):
    change_what_the_docker_jobs_run_for(ci.root)
    missing = {
        "docker": {
            "optional": AREAS["docker"].optional,
            "problems": ["docker is not installed"],
        }
    }

    result, lines = ci("--docker", *DOCKER_JOBS, DOCTOR=json.dumps(missing))

    assert result.returncode == 0, result.stdout
    for name in DOCKER_JOBS:
        assert summary_of(result.stdout, name) == (
            f"⏭  {name}: needs the docker: docker is not installed"
        )
    # Docker is the doctor's to ask about.
    assert lines == []


def test_a_job_in_docker_named_on_its_own_runs_without_docker_asked_for(ci):
    change_what_the_docker_jobs_run_for(ci.root)

    result, _ = ci(*DOCKER_JOBS)

    assert "⏭" not in verdicts(result.stdout).values()


def test_the_devcontainer_is_skipped_when_it_is_the_same_as_mains(ci):
    result, lines = ci("devcontainer")

    assert result.returncode == 0, result.stdout
    assert summary_of(result.stdout, "devcontainer") == (
        f"⏭  devcontainer: {DEVCONTAINER.changed} is the same as main's, "
        "so CI skips it too"
    )
    assert lines == []


def test_the_devcontainer_runs_for_a_change_not_yet_committed(ci):
    change_what_it_runs_for(ci.root, DEVCONTAINER)

    result, _ = ci("devcontainer")

    assert verdicts(result.stdout) == {"devcontainer": "✅"}


def test_the_devcontainer_runs_for_a_change_committed_on_a_branch(ci):
    git = [
        "git",
        "-C",
        str(ci.root),
        "-c",
        "user.name=spam",
        "-c",
        "user.email=-",
    ]
    subprocess.run([*git, "switch", "-q", "-c", "spam"], check=True)
    change_what_it_runs_for(ci.root, DEVCONTAINER)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "eggs"], check=True)

    result, _ = ci("devcontainer")

    assert verdicts(result.stdout) == {"devcontainer": "✅"}


def test_the_devcontainer_is_skipped_for_a_change_main_made_since_the_branch(
    ci,
):
    git = [
        "git",
        "-C",
        str(ci.root),
        "-c",
        "user.name=spam",
        "-c",
        "user.email=-",
    ]
    subprocess.run([*git, "branch", "spam"], check=True)
    change_what_it_runs_for(ci.root, DEVCONTAINER)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "eggs"], check=True)
    subprocess.run([*git, "switch", "-q", "spam"], check=True)

    result, _ = ci("devcontainer")

    assert verdicts(result.stdout) == {"devcontainer": "⏭"}


@pytest.mark.skipif(platform.system() == "Linux", reason="for another system")
def test_off_linux_the_jobs_for_linux_alone_are_skipped_saying_so(ci):
    result, lines = ci(*LINUX_JOBS)

    assert result.returncode == 0, result.stdout
    for name in LINUX_JOBS:
        assert summary_of(result.stdout, name) == (
            f"⏭  {name}: runs on Linux alone"
        )
    assert lines == []


@pytest.mark.skipif(platform.system() != "Linux", reason="for Linux")
def test_on_linux_the_jobs_for_linux_alone_run(ci):
    result, _ = ci(*LINUX_JOBS)

    assert verdicts(result.stdout) == dict.fromkeys(LINUX_JOBS, "✅")


def test_the_list_shows_what_each_job_needs_and_why_one_cannot_run_here(ci):
    result, _ = ci("--list")

    entries = listed(result.stdout)
    for job in JOBS:
        for need in job.needs:
            assert need in needs_line(entries[job.name])
    for name in DOCKER_JOBS:
        assert "⏭" in entries[name]
        assert "--docker" in entries[name]


def test_the_list_says_which_jobs_this_machine_is_missing_something_for(ci):
    missing = {
        "edk2": {"problems": ["iasl is not installed"]},
        "qbox": {"optional": True, "problems": ["meson is not installed"]},
    }

    result, _ = ci("--list", DOCTOR=json.dumps(missing))

    entries = listed(result.stdout)
    assert "❌ at the check of the edk2" in entries["firmware-edk2"]
    assert "⏭  needs the qbox: meson is not installed" in entries["qbox-build"]


def test_run_in_ci_does_not_ask_the_doctor(ci):
    ci("run", "test")

    assert ci.doctor_asked() == []


def test_when_the_patches_change_the_patched_dependencies_are_dropped(ci):
    ci("lint")
    (ci.root / "cmake" / "patches" / "eggs-fix.patch").write_text("two\n")
    dependencies = make_dependencies(ci.root)

    ci("lint")

    assert dropped(dependencies) == PATCHED


def test_when_the_patches_are_the_same_nothing_is_dropped(ci):
    ci("lint")
    dependencies = make_dependencies(ci.root)

    ci("lint")

    assert dropped(dependencies) == set()


def test_a_tree_from_before_any_run_is_taken_to_be_stale(ci):
    dependencies = make_dependencies(ci.root)

    ci("lint")

    assert dropped(dependencies) == PATCHED


def test_clean_drops_the_patched_dependencies_though_the_patches_are_the_same(
    ci,
):
    ci("lint")
    dependencies = make_dependencies(ci.root)

    ci("--clean", "lint")

    assert dropped(dependencies) == PATCHED


def test_run_in_ci_leaves_the_dependencies_alone_and_keeps_no_record(ci):
    dependencies = make_dependencies(ci.root)

    ci("run", "lint")

    assert dropped(dependencies) == set()
    ci("lint")
    assert dropped(dependencies) == PATCHED


@pytest.mark.parametrize("job", ["coverage", "sanitizers"])
@pytest.mark.parametrize("fails", [False, True], ids=["passes", "fails"])
def test_after_a_job_that_configures_the_dev_tree_otherwise_it_is_put_back(
    ci, job, fails
):
    ci(job, FAIL_ON="--build" if fails else "@")

    assert ci.lines()[-1] == "uv run cmake --preset dev"


def test_after_a_job_that_configures_the_dev_tree_for_dev_it_is_left_as_is(
    ci,
):
    _, lines = ci("test")

    assert lines.count("uv run cmake --preset dev") == 1


def test_a_dev_tree_that_cannot_be_put_back_is_named_in_a_warning(ci):
    result, _ = ci("coverage", FAIL_ON="dev")

    assert "⚠️  build/dev was not configured for dev again" in result.stdout


def test_on_a_terminal_a_job_that_passes_is_green_and_one_that_fails_red(ci):
    sent = ci.on_a_terminal("lint", "firmware-rom", FAIL_ON="rom")

    assert f"{GREEN}✅ lint" in sent
    assert f"{RED}❌ firmware-rom" in sent


def test_with_no_color_asked_for_a_terminal_is_sent_no_color(ci):
    sent = ci.on_a_terminal("lint", "firmware-rom", FAIL_ON="rom", NO_COLOR="1")

    assert "\x1b[" not in sent


def test_output_to_a_pipe_is_not_colored(ci):
    result, _ = ci("lint", "firmware-rom", FAIL_ON="rom")

    assert "\x1b[" not in result.stdout


def test_tidy_configures_the_dev_tree_and_runs_clang_tidy_then_the_header_check(
    ci,
):
    _, lines = ci("run", "tidy")

    assert lines == [
        "uv run cmake --preset dev",
        "uv run cmake --build --preset dev --target tidy",
        "uv run cmake --build --preset dev --target check_headers",
    ]


def test_twister_builds_the_dev_tree_checks_its_files_then_runs_the_suites(
    ci,
):
    _, lines = ci("run", "twister")

    assert lines == [
        "uv run cmake --preset dev",
        "uv run cmake --build --preset dev",
        "uv run pytest tests/python/test_twister_boards.py",
        "uv run pytest tests/tooling -k twister",
        "uv run firmware/twister.py --suites",
    ]


def test_coverage_builds_its_target_in_the_coverage_tree(ci):
    _, lines = ci("run", "coverage")

    assert lines == [
        "uv run cmake --preset coverage",
        "uv run cmake --build --preset coverage --target coverage",
    ]


def test_sanitizers_builds_and_tests_the_asan_tree(ci):
    _, lines = ci("run", "sanitizers")

    assert lines == [
        "uv run cmake --preset asan",
        "uv run cmake --build --preset asan",
        "uv run ctest --preset asan",
    ]


def test_qbox_build_builds_qbox(ci):
    _, lines = ci("run", "qbox-build")

    assert lines == ["uv run tools/build_qbox.py"]


def test_qbox_tests_the_qbox_tree_needing_the_firmware_then_runs_the_suites_on_qboxs_cpu(
    ci,
):
    ci("run", "qbox")

    commands = [(c["command"], c["env"]) for c in ci.commands()]
    assert commands == [
        ("uv run cmake --preset qbox", {}),
        ("uv run cmake --build --preset qbox", {}),
        ("uv run ctest --preset qbox", {"SOCPUPPET_REQUIRE_FIRMWARE": "1"}),
        (
            "uv run firmware/twister.py --suites -p socpuppet_host",
            {"SOCPUPPET_CPU": "qbox_cpu"},
        ),
    ]


def test_qbox_tidy_runs_clang_tidy_then_the_header_check_on_the_qbox_tree(ci):
    _, lines = ci("run", "qbox-tidy")

    assert lines == [
        "uv run cmake --preset qbox",
        "uv run cmake --build --preset qbox --target tidy",
        "uv run cmake --build --preset qbox --target check_headers",
    ]


def test_wheel_here_builds_this_machines_wheel_from_an_sdist_and_tests_it(ci):
    result, _ = ci("wheel", makes=ONE_WHEEL)

    assert result.returncode == 0, result.stdout
    commands = [step["command"].split() for step in ci.commands()]
    assert commands[0][:3] == ["uv", "build", "--sdist"]
    build = commands[1]
    assert build[:3] == ["uv", "run", "cibuildwheel"]
    only = build[build.index("--only") + 1]
    assert only.startswith(f"{TAG}-")
    assert only.endswith(platform.machine())
    assert SDIST in build
    assert commands[2:] == [
        ["uv", "run", "python", "tools/check_wheel.py", OUR_WHEEL],
        ["test_wheel.py", "uv", OUR_WHEEL],
        ["test_wheel.py", "pip", OUR_WHEEL],
    ]


def test_wheel_here_leaves_testing_the_wheel_to_test_wheel_py(ci):
    ci("wheel", makes=ONE_WHEEL)

    # test_wheel.py tests the same wheel, and boots the firmware too.
    assert ci.command_with("cibuildwheel")["env"]["CIBW_TEST_SKIP"] == "*"


# A Mac builds its wheel outside a container, beside ccache's own cache.
ON_LINUX_ONLY = pytest.mark.skipif(
    platform.system() != "Linux", reason="Linux builds its wheel in a container"
)


@ON_LINUX_ONLY
def test_wheel_here_keeps_the_containers_compiler_cache_in_build_ccache(ci):
    ci("wheel", makes=ONE_WHEEL)

    env = ci.command_with("cibuildwheel")["env"]
    # The container sees this machine's files under /host.
    assert env["CCACHE_DIR"] == f"/host{ci.root}/build/ccache"


@ON_LINUX_ONLY
def test_wheel_here_leaves_the_containers_compiler_cache_for_anyone_to_remove(
    ci,
):
    ci("wheel", makes=ONE_WHEEL)

    # The container runs as root.
    env = ci.command_with("cibuildwheel")["env"]
    assert env["CCACHE_UMASK"] == "000"


def test_wheel_installs_boot_the_firmware_in_build_firmware(ci):
    ci("wheel", makes=ONE_WHEEL)

    installs = [
        step for step in ci.commands() if "test_wheel.py" in step["command"]
    ]
    assert installs
    for install in installs:
        assert install["env"] == {
            "SOCPUPPET_REQUIRE_FIRMWARE": "1",
            "SOCPUPPET_FIRMWARE_DIR": str(ci.root / "build" / "firmware"),
        }


def test_wheel_in_ci_builds_every_wheel_in_place_checks_each_and_installs_ours(
    ci,
):
    wheels = [
        f"build/wheelhouse/socpuppet-0.0.1-{tag}-spam.whl"
        for tag in sorted({"cp312", TAG, "cp314"})
    ]
    ours = f"build/wheelhouse/socpuppet-0.0.1-{TAG}-spam.whl"

    ci("run", "wheel", makes={"cibuildwheel": wheels})

    assert [c["command"] for c in ci.commands()] == [
        "uv run cibuildwheel --output-dir build/wheelhouse",
        "uv run python tools/check_wheel.py " + " ".join(wheels),
        f"test_wheel.py uv {ours}",
        f"test_wheel.py pip {ours}",
    ]


@pytest.mark.parametrize(
    "where", [("wheel",), ("run", "wheel")], ids=["here", "in CI"]
)
def test_a_wheel_left_by_an_earlier_run_is_not_checked(ci, where):
    old = ci.root / "build" / "wheelhouse" / "socpuppet-0.0.0-spam.whl"
    old.parent.mkdir(parents=True)
    old.touch()

    _, lines = ci(*where, makes=ONE_WHEEL)

    checked = next(line for line in lines if "check_wheel.py" in line)
    assert checked == f"uv run python tools/check_wheel.py {OUR_WHEEL}"


@pytest.mark.parametrize(
    "where", [("wheel",), ("run", "wheel")], ids=["here", "in CI"]
)
def test_a_step_whose_files_are_not_there_fails_and_names_what_it_wanted(
    ci, where
):
    result, _ = ci(*where)

    assert result.returncode == 1
    assert "no file matches build/wheelhouse/" in result.stdout


def test_devcontainer_builds_and_tests_the_linux_tree_in_docker(ci):
    _, lines = ci("run", "devcontainer")

    assert lines == [
        "devcontainer.py uv run cmake --preset linux",
        "devcontainer.py uv run cmake --build --preset linux",
        "devcontainer.py uv run ctest --preset linux",
    ]


def write_stand_in(path, program=STAND_IN):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{program}")
    path.chmod(0o755)


# The dependencies a run finds in the build trees: those of socpuppet's
# trees (the presets' binaryDir), as FetchContent names them, and QBox's own
# two (tools/build_qbox.py's tree).
DEPENDENCY_DIRECTORIES = [
    f"{tree}/_deps/{name}-{part}"
    for tree in ("build/dev", "build/qbox-dev")
    for name in ("spam", "eggs", "ham_core")
    for part in ("src", "build", "subbuild")
] + [
    f"build/qbox/build/_deps/{name}-{part}"
    for name in ("rpclib", "libqemu")
    for part in ("src", "build", "subbuild")
]
# The ones that are patched: FetchContent's that have a PATCH_COMMAND, and
# QBox's rpclib, which CPM patches. libqemu is patched by
# tools/build_qbox.py, which keeps its own account.
PATCHED = {
    directory
    for directory in DEPENDENCY_DIRECTORIES
    if "/eggs-" in directory
    or "/ham_core-" in directory
    or "/rpclib-" in directory
}


def make_dependencies(root):
    """Fill the build trees with dependencies; returns their directories."""
    for directory in DEPENDENCY_DIRECTORIES:
        (root / directory).mkdir(parents=True)
        (root / directory / "file").write_text("old\n")
    return {directory: root / directory for directory in DEPENDENCY_DIRECTORIES}


def dropped(dependencies):
    return {name for name, path in dependencies.items() if not path.exists()}


def git(root, *args):
    who = ["-c", "user.name=spam", "-c", "user.email=-"]
    subprocess.run(["git", "-C", str(root), *who, *args], check=True)


def commit_everything(root):
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "spam")


def change_what_it_runs_for(root, job):
    """Add a file where a job that runs for a change looks for one."""
    path = root / job.changed / "spam"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("eggs\n")


def change_what_the_docker_jobs_run_for(root):
    for name in DOCKER_JOBS:
        if JOBS_BY_NAME[name].changed:
            change_what_it_runs_for(root, JOBS_BY_NAME[name])


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
    """The files of a working tree, and not of git's own store, which git
    may tidy by itself after a commit."""
    return sorted(
        path
        for path in directory.rglob("*")
        if ".git" not in path.relative_to(directory).parts
    )


def command_to_run_here(output):
    """The command a job's log says runs it on a developer's machine."""
    marker = "To run this on your machine:"
    line = next(line for line in output.splitlines() if marker in line)
    return line.split(marker, 1)[1].strip()


def verdicts(output):
    """What the summary at the end of a run says of each job: ✅, ❌, ⏭ or 🛑."""
    summary = output.split("🧦 Summary", 1)[1]
    found = {}
    for line in summary.splitlines()[1:]:
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
        " ".join([Path(step.argv[0]).name, *map(str, step.argv[1:])])
        for step in JOBS_BY_NAME[name].steps_for(RUNNER_MODULE.Mode.HERE)
    ]


def before_any_job_started(output):
    """What a run said before the first of its jobs started."""
    return output.split("🚀", 1)[0]


def summary_of(output, name):
    """The line the summary at the end of a run has for one job."""
    summary = output.split("🧦 Summary", 1)[1]
    return next(
        line.strip()
        for line in summary.splitlines()[1:]
        if line.split()[1:2] in ([name], [f"{name}:"])
    )


def listed(output):
    """What --list says of each job: {name: its lines, as one text}."""
    entries = {}
    for line in output.splitlines():
        if line and not line.startswith(" "):
            name = line.split()[0]
            entries[name] = ""
        entries[name] += line + "\n"
    return entries


def needs_line(entry):
    return next(
        line for line in entry.splitlines() if line.strip().startswith("needs")
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
