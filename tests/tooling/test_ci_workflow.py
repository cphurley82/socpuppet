""".github/workflows/ci.yml, held to the jobs tools/ci.py runs.

The workflow is written by hand, and each of its jobs is a thin wrapper:
GitHub's plumbing (a checkout, packages, caches, artifacts) around a step
that runs `uv run python tools/ci.py run JOB`. These tests keep the two to
the same jobs, so that what a developer runs here is what CI runs.
"""

import importlib.util
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
# How a job of the workflow runs a job of the runner.
RUN = "uv run python tools/ci.py run "
# A GitHub runner of Ubuntu, as a label names it.
UBUNTU = re.compile(r"ubuntu-\d+\.\d+(?:-arm)?")
# The key of a cache kept under the key its restore step looked for.
KEPT = re.compile(r"\$\{\{ steps\.\w+\.outputs\.cache-primary-key \}\}")


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
# which links the most of the system's libraries. QBox's job restores the
# same Zephyr and SDK there as on the default (PORTABLE_CACHES).
OLDEST_UBUNTU = "ubuntu-24.04"
ON_THE_OLDEST_UBUNTU_TOO = {
    "test",
    "qbox-build",
    "qbox",
}
# The caches whose contents run on any Linux of the same processor, as on
# any Mac: the Zephyr SDK's prebuilt tools, its LLVM, and Zephyr with a venv
# on uv's own Python. One copy serves every Ubuntu.
PORTABLE_CACHES = {"sdk", "zephyr", "llvm"}


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
        ubuntus = ubuntus_of(job)
        assert ubuntus & DEFAULT_UBUNTUS, name
        assert ubuntus <= allowed, name


def test_the_named_few_run_on_the_oldest_ubuntu_beside_the_default():
    for name in ON_THE_OLDEST_UBUNTU_TOO:
        assert {DEFAULT_UBUNTU, OLDEST_UBUNTU} <= set(
            runners(WORKFLOW[name])
        ), name


def test_a_cache_key_names_an_ubuntu_only_in_a_job_that_runs_on_it_alone():
    # What a cache holds was built for the runner that made it, and a job
    # on another Ubuntu would take it for its own. A job on several
    # runners names its own in a key with matrix.os.
    for name, job in WORKFLOW.items():
        for key, ubuntus in ubuntus_in_cache_keys(job):
            assert not ubuntus or ubuntus == set(runners(job)), f"{name}: {key}"


def test_a_portable_cache_is_keyed_on_system_and_processor_not_on_an_ubuntu():
    seen = set()
    for name, job in WORKFLOW.items():
        for key in cache_keys(job):
            cache = cache_named_by(key)
            if cache in PORTABLE_CACHES:
                seen.add(cache)
                named = {
                    word
                    for word in ("runner.os", "runner.arch", "matrix.os")
                    if word in key
                }
                assert named == {"runner.os", "runner.arch"}, f"{name}: {key}"
                assert not UBUNTU.search(key), f"{name}: {key}"
    assert seen == PORTABLE_CACHES


def test_a_job_on_several_ubuntu_runners_keys_what_it_builds_on_the_one_it_runs_on():
    # A key that names only the system, or ubuntu-latest, is the same on
    # each Ubuntu runner, 24.04 and 26.04, Intel and Arm, and each leg would
    # take another's build for its own.
    checked = set()
    for name, job in WORKFLOW.items():
        if len(ubuntus_of(job)) < 2:
            continue
        checked.add(name)
        for key in keys_of_what_it_builds(job):
            assert "matrix.os" in key, f"{name}: {key}"
    assert checked >= ON_THE_OLDEST_UBUNTU_TOO


def test_the_devcontainers_image_is_the_default_ubuntu():
    dockerfile = REPO / ".devcontainer" / "Dockerfile"
    version = DEFAULT_UBUNTU.removeprefix("ubuntu-")
    assert set(base_images(dockerfile)) == {f"ubuntu:{version}"}


def base_images(dockerfile):
    """The image each FROM instruction of a Dockerfile builds on."""
    for line in dockerfile.read_text().splitlines():
        words = line.split()
        if words and words[0].upper() == "FROM":
            yield next(word for word in words[1:] if not word.startswith("--"))


def ubuntus_in_cache_keys(job):
    """Each cache key of a job's steps, with the Ubuntu runners it names."""
    for key in cache_keys(job):
        yield key, set(UBUNTU.findall(key))


def cache_keys(job):
    """The key of each cache a job of the workflow keeps or restores."""
    for step in job["steps"]:
        if "key" in step.get("with", {}):
            yield step["with"]["key"]


def keys_of_what_it_builds(job):
    """A job's cache keys, less the portable caches and the saves that keep
    a restore's own key."""
    for key in cache_keys(job):
        if cache_named_by(key) not in PORTABLE_CACHES and not KEPT.fullmatch(
            key
        ):
            yield key


def ubuntus_of(job):
    """The Ubuntu runners a job of the workflow runs on."""
    return {runner for runner in runners(job) if UBUNTU.fullmatch(runner)}


def cache_named_by(key):
    """The cache a key is for: its first word, as in sdk-, zephyr-, llvm-."""
    return key.split("-")[0]


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
