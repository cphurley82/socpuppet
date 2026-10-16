"""tools/ci.py, which runs CI's jobs: every one on this machine, or one in CI.

The runner is run for real in a throwaway copy of the repository, with
stand-ins for uv and the scripts the jobs call. Each stand-in writes the
command it was given to a log, so the tests can say what the runner ran, and
in what order, without building anything.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "tools" / "ci.py"

# A program that logs its command line, says it on its output, and exits
# with the status the test asked for: FAIL_ON names a word, and a command
# that holds it fails. Each command is also written to the log's .json, with
# socpuppet's variables.
STAND_IN = """\
import json, os, sys
command = " ".join([os.path.basename(sys.argv[0]), *sys.argv[1:]])
with open(os.environ["LOG"], "a") as log:
    log.write(command + "\\n")
print("spam spam spam " + command)
with open(os.environ["LOG"] + ".json", "a") as log:
    log.write(json.dumps({
        "command": command,
        "env": {k: v for k, v in os.environ.items()
                if k.startswith("SOCPUPPET_")},
    }) + "\\n")
sys.exit(1 if os.environ.get("FAIL_ON", "@") in sys.argv[1:] else 0)
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


@pytest.fixture
def ci(tmp_path):
    """Run the runner in a copy of the repo; returns run(*args, **env).

    run returns the finished process and the commands the stand-ins were
    given, in order. run.root is the copy, and run.commands() the commands
    with their variables.
    """
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    shutil.copy(RUNNER, root / "tools" / "ci.py")
    for script in SCRIPTS:
        write_stand_in(root / script)
    bin_directory = tmp_path / "bin"
    write_stand_in(bin_directory / "uv")
    log = tmp_path / "log"

    def run(*args, **env):
        result = subprocess.run(
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
        return result, log.read_text().splitlines() if log.exists() else []

    def commands():
        path = Path(f"{log}.json")
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    run.root = root
    run.commands = commands
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


def write_stand_in(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{STAND_IN}")
    path.chmod(0o755)


def files_in(directory):
    return sorted(directory.rglob("*"))


def command_to_run_here(output):
    """The command a job's log says runs it on a developer's machine."""
    marker = "To run this on your machine:"
    line = next(line for line in output.splitlines() if marker in line)
    return line.split(marker, 1)[1].strip()


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
