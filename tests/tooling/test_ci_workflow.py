""".github/workflows/ci.yml, held to the jobs tools/ci.py runs.

The workflow is written by hand, and each of its jobs is a thin wrapper:
GitHub's plumbing (a checkout, packages, caches, artifacts) around a step
that runs `uv run python tools/ci.py run JOB`. These tests keep the two to
the same jobs, so that what a developer runs here is what CI runs.
"""

import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
# How a job of the workflow runs a job of the runner.
RUN = "uv run python tools/ci.py run "


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "ci", REPO / "tools" / "ci.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_runner()
JOBS = {job.name: job for job in RUNNER.JOBS}
WORKFLOW = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]

# A job that builds QBox, or runs on what that built, is given three hours:
# half GitHub's own limit, and four times the 45 minutes that the first run
# of the QBox nightly this workflow took over took, QBox built from nothing
# included. A run that takes longer has gone wrong.
QBOX_TIME_LIMIT = 180

# The Ubuntu a job runs on unless it says otherwise, on Intel or on Arm.
DEFAULT_UBUNTU = "ubuntu-26.04"
DEFAULT_UBUNTUS = {DEFAULT_UBUNTU, f"{DEFAULT_UBUNTU}-arm"}
# The oldest Ubuntu socpuppet supports, with an older GCC and older system
# libraries. These jobs run on it too: the build and the tests, and QBox,
# which links the most of the system's libraries, with the caches of
# Zephyr and its SDK that QBox's job restores.
OLDEST_UBUNTU = "ubuntu-24.04"
ON_THE_OLDEST_UBUNTU_TOO = {
    "fetch-sdk",
    "fetch-zephyr",
    "test",
    "qbox-build",
    "qbox",
}


def test_ci_is_the_only_workflow():
    assert sorted(path.name for path in WORKFLOWS.iterdir()) == ["ci.yml"]


def test_the_workflow_has_a_job_for_each_job_of_the_runner():
    assert set(WORKFLOW) == set(JOBS)


def test_each_job_of_the_workflow_waits_for_the_jobs_it_needs():
    for name, job in WORKFLOW.items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        assert set(needs) == set(JOBS[name].needs), name


def test_each_job_of_the_workflow_ends_by_running_itself_with_the_runner():
    for name, job in WORKFLOW.items():
        named = jobs_run(job)
        assert named, name
        assert named[-1] == name


def test_each_job_of_the_workflow_runs_no_other_job_but_one_it_needs():
    for name, job in WORKFLOW.items():
        assert set(jobs_run(job)[:-1]) <= RUNNER.needed_by(JOBS[name]), name


def test_no_other_step_runs_what_a_job_of_the_runner_runs():
    for name, job in WORKFLOW.items():
        for step in job["steps"]:
            command = step.get("run", "")
            if command.startswith(RUN):
                continue
            for program in PROGRAMS:
                assert program not in command, f"{name}: {command}"


def test_the_jobs_with_qbox_and_only_those_have_a_time_limit():
    with_qbox = {
        name
        for name, job in JOBS.items()
        if name == "qbox-build" or "qbox-build" in RUNNER.needed_by(job)
    }
    limits = {
        name: job["timeout-minutes"]
        for name, job in WORKFLOW.items()
        if "timeout-minutes" in job
    }
    assert limits == dict.fromkeys(with_qbox, QBOX_TIME_LIMIT)


def test_a_job_on_several_machines_runs_on_each_whatever_the_others_do():
    for name, job in WORKFLOW.items():
        if "matrix" in job.get("strategy", {}):
            assert job["strategy"]["fail-fast"] is False, name


def test_each_job_runs_on_the_default_ubuntu_and_only_the_named_few_on_the_oldest_too():
    for name, job in WORKFLOW.items():
        allowed = DEFAULT_UBUNTUS | (
            {OLDEST_UBUNTU} if name in ON_THE_OLDEST_UBUNTU_TOO else set()
        )
        ubuntus = {
            runner for runner in runners(job) if runner.startswith("ubuntu")
        }
        assert ubuntus & DEFAULT_UBUNTUS, name
        assert ubuntus <= allowed, name


def test_the_named_few_run_on_the_oldest_ubuntu_beside_the_default():
    for name in ON_THE_OLDEST_UBUNTU_TOO:
        assert {DEFAULT_UBUNTU, OLDEST_UBUNTU} <= set(
            runners(WORKFLOW[name])
        ), name


def runners(job):
    """The runners a job of the workflow runs on: its matrix's, or its own."""
    if job["runs-on"] == "${{ matrix.os }}":
        return job["strategy"]["matrix"]["os"]
    return [job["runs-on"]]


def jobs_run(job):
    """The jobs a job of the workflow runs with the runner, in order."""
    return [
        word
        for step in job["steps"]
        if step.get("run", "").startswith(RUN)
        for word in step["run"].removeprefix(RUN).split()
    ]


def program_of(step):
    """What a step of the runner's runs: a tool, or a script of ours."""
    words = [str(word) for word in step.argv]
    if words[:2] == ["uv", "run"]:
        words = words[2:]
    elif words[0] == "uv":
        return " ".join(words[:2])
    if words[0] == "python":
        words = words[1:]
    return words[0]


# Everything the runner's jobs run, which only the runner may.
PROGRAMS = {
    program_of(step)
    for job in JOBS.values()
    for mode in RUNNER.Mode
    for step in job.steps_for(mode)
}
