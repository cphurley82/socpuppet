""".github/workflows, held to the jobs tools/ci.py runs.

Each workflow is written by hand, and each of its jobs is a thin wrapper:
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
TIER = RUNNER.Tier
# Each workflow, and its jobs, by its file's name.
WORKFLOW_DEFINITIONS = {
    path.name: yaml.safe_load(path.read_text())
    for path in sorted(WORKFLOWS.glob("*.yml"))
}
WORKFLOW_FILES = {
    file: definition["jobs"]
    for file, definition in WORKFLOW_DEFINITIONS.items()
}
# Every job of every workflow: where it is, as file: job, its name, and it.
WORKFLOW_JOBS = [
    (f"{file}: {name}", name, job)
    for file, jobs in WORKFLOW_FILES.items()
    for name, job in jobs.items()
]

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


# A job of the quick tier that runs some of what one of the nightly tier
# runs, by the name of the nightly's: the quick tests are the dev tests
# but the long ones.
NIGHTLY_COUNTERPART = {"test-quick": "test"}


def test_there_is_a_workflow_for_each_tier_and_no_other():
    assert sorted(path.name for path in WORKFLOWS.iterdir()) == sorted(
        tier.value for tier in TIER
    )


def test_each_workflow_has_a_job_for_each_job_of_its_tier_and_no_other():
    for tier in TIER:
        assert set(WORKFLOW_FILES[tier.value]) == {
            name for name, job in JOBS.items() if tier in job.tiers
        }, tier.value


def test_a_job_in_both_tiers_is_the_same_in_both_workflows_but_for_its_machines():
    # Word for word, comments too, so that the two copies cannot drift.
    quick = WORKFLOW_FILES[TIER.QUICK.value]
    nightly = WORKFLOW_FILES[TIER.NIGHTLY.value]
    for name in set(quick) & set(nightly):
        assert without_its_machines(TIER.QUICK, name) == without_its_machines(
            TIER.NIGHTLY, name
        ), name


def test_each_machine_the_quick_tier_runs_a_job_on_the_nightly_runs_it_on_too():
    quick = WORKFLOW_FILES[TIER.QUICK.value]
    nightly = WORKFLOW_FILES[TIER.NIGHTLY.value]
    for name, job in quick.items():
        counterpart = nightly[NIGHTLY_COUNTERPART.get(name, name)]
        assert set(runners(job)) <= set(runners(counterpart)), name


def test_a_push_to_main_and_a_pull_request_start_the_quick_tier():
    triggers = triggers_of(TIER.QUICK)
    assert "main" in triggers["push"]["branches"]
    assert "pull_request" in triggers


def test_only_a_schedule_or_a_person_starts_the_nightly_tier():
    triggers = triggers_of(TIER.NIGHTLY)
    assert set(triggers) == {"schedule", "workflow_dispatch"}


def test_neither_tier_queues_behind_the_other():
    # Runs of one concurrency group wait for each other, and a newer one
    # waiting takes the place of an older one. A group's fixed part, before
    # anything GitHub fills in, keeps one tier's apart from the other's.
    quick = fixed_part_of_group(TIER.QUICK)
    nightly = fixed_part_of_group(TIER.NIGHTLY)
    assert not quick.startswith(nightly)
    assert not nightly.startswith(quick)


def test_each_job_of_a_workflow_waits_for_the_jobs_it_needs():
    for where, name, job in WORKFLOW_JOBS:
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        assert set(needs) == set(JOBS[name].needs), where


def test_each_job_of_a_workflow_ends_by_running_itself_with_the_runner():
    for where, name, job in WORKFLOW_JOBS:
        named = jobs_run(job)
        assert named, where
        assert named[-1] == name, where


def test_each_job_of_a_workflow_runs_no_other_job_but_one_it_needs():
    for where, name, job in WORKFLOW_JOBS:
        assert set(jobs_run(job)[:-1]) <= RUNNER.needed_by(JOBS[name]), where


def test_no_other_step_runs_what_a_job_of_the_runner_runs():
    for where, _, job in WORKFLOW_JOBS:
        for step in job["steps"]:
            command = step.get("run", "")
            if command.startswith(RUN):
                continue
            for program in PROGRAMS:
                assert program not in command, f"{where}: {command}"


def test_the_jobs_with_qbox_and_only_those_have_a_time_limit():
    with_qbox = {
        name
        for name, job in JOBS.items()
        if name == "qbox-build" or "qbox-build" in RUNNER.needed_by(job)
    }
    for file, jobs in WORKFLOW_FILES.items():
        limits = {
            name: job["timeout-minutes"]
            for name, job in jobs.items()
            if "timeout-minutes" in job
        }
        assert limits == dict.fromkeys(
            with_qbox & set(jobs), QBOX_TIME_LIMIT
        ), file


def test_a_job_on_several_machines_runs_on_each_whatever_the_others_do():
    for where, _, job in WORKFLOW_JOBS:
        if "matrix" in job.get("strategy", {}):
            assert job["strategy"]["fail-fast"] is False, where


def test_each_job_runs_on_the_default_ubuntu_and_only_the_named_few_on_the_oldest_too():
    for where, name, job in WORKFLOW_JOBS:
        allowed = DEFAULT_UBUNTUS | (
            {OLDEST_UBUNTU} if name in ON_THE_OLDEST_UBUNTU_TOO else set()
        )
        ubuntus = ubuntus_of(job)
        assert ubuntus & DEFAULT_UBUNTUS, where
        assert ubuntus <= allowed, where


def test_the_named_few_run_on_the_oldest_ubuntu_beside_the_default_every_night():
    nightly = WORKFLOW_FILES[TIER.NIGHTLY.value]
    for name in ON_THE_OLDEST_UBUNTU_TOO:
        assert {DEFAULT_UBUNTU, OLDEST_UBUNTU} <= set(runners(nightly[name])), (
            name
        )


def test_a_cache_key_names_an_ubuntu_only_in_a_job_that_runs_on_it_alone():
    # What a cache holds was built for the runner that made it, and a job
    # on another Ubuntu would take it for its own. A job on several
    # runners names its own in a key with matrix.os.
    for where, _, job in WORKFLOW_JOBS:
        for key, ubuntus in ubuntus_in_cache_keys(job):
            assert not ubuntus or ubuntus == set(runners(job)), (
                f"{where}: {key}"
            )


def test_a_portable_cache_is_keyed_on_system_and_processor_not_on_an_ubuntu():
    for file, jobs in WORKFLOW_FILES.items():
        seen = set()
        for name, job in jobs.items():
            for key in cache_keys(job):
                cache = cache_named_by(key)
                if cache in PORTABLE_CACHES:
                    seen.add(cache)
                    named = {
                        word
                        for word in ("runner.os", "runner.arch", "matrix.os")
                        if word in key
                    }
                    assert named == {"runner.os", "runner.arch"}, (
                        f"{file}: {name}: {key}"
                    )
                    assert not UBUNTU.search(key), f"{file}: {name}: {key}"
        assert seen == PORTABLE_CACHES, file


def test_a_job_on_several_ubuntu_runners_keys_what_it_builds_on_the_one_it_runs_on():
    # A key that names only the system, or ubuntu-latest, is the same on
    # each Ubuntu runner, 24.04 and 26.04, Intel and Arm, and each leg would
    # take another's build for its own.
    checked = set()
    for where, name, job in WORKFLOW_JOBS:
        if len(ubuntus_of(job)) < 2:
            continue
        checked.add(name)
        for key in keys_of_what_it_builds(job):
            assert "matrix.os" in key, f"{where}: {key}"
    assert checked >= ON_THE_OLDEST_UBUNTU_TOO


def test_the_linux_firmware_is_cached_and_handed_on_with_its_initramfs():
    for file, jobs in WORKFLOW_FILES.items():
        kept = paths_kept_by(jobs["firmware-linux"])
        assert set(kept) == {"actions/cache", "actions/upload-artifact"}, file
        for paths in kept.values():
            assert "build/firmware/initramfs.cpio" in paths, file


def test_a_change_to_what_the_initramfs_is_made_of_is_a_new_linux_cache():
    for file, jobs in WORKFLOW_FILES.items():
        (key,) = keys_of_what_it_builds(jobs["firmware-linux"])
        assert "firmware/initramfs/**" in hashed_by(key), file


def test_the_runner_builds_in_the_devcontainers_image_on_the_default_ubuntu_and_the_oldest():
    assert set(RUNNER.UBUNTUS) == {
        name.removeprefix("ubuntu-") for name in (DEFAULT_UBUNTU, OLDEST_UBUNTU)
    }


def test_the_devcontainers_image_is_the_default_ubuntu():
    dockerfile = REPO / ".devcontainer" / "Dockerfile"
    version = DEFAULT_UBUNTU.removeprefix("ubuntu-")
    assert set(base_images(dockerfile)) == {f"ubuntu:{version}"}


def without_its_machines(tier, name):
    """A job's text in a tier's workflow, less the line of its matrix's
    machines."""
    text = (WORKFLOWS / tier.value).read_text()
    start = re.search(rf"^  {re.escape(name)}:$", text, re.MULTILINE).end()
    following = re.compile(r"^  \S", re.MULTILINE).search(text, start)
    block = text[start : following.start() if following else len(text)]
    return [
        line
        for line in block.splitlines()
        if not line.strip().startswith("os: ")
    ]


def fixed_part_of_group(tier):
    """A tier's concurrency group up to the first `${{`, GitHub's to fill."""
    group = WORKFLOW_DEFINITIONS[tier.value]["concurrency"]["group"]
    return group.split("${{")[0]


def triggers_of(tier):
    """What starts a tier's workflow: its `on`, which YAML reads as True."""
    return WORKFLOW_DEFINITIONS[tier.value][True]


def base_images(dockerfile):
    """The image each FROM instruction of a Dockerfile builds on, with each
    ARG before it as its default."""
    defaults = {}
    for line in dockerfile.read_text().splitlines():
        words = line.split()
        if words and words[0].upper() == "ARG" and "=" in words[1]:
            name, default = words[1].split("=", 1)
            defaults[name] = default
        if words and words[0].upper() == "FROM":
            image = next(
                word for word in words[1:] if not word.startswith("--")
            )
            yield re.sub(r"\$\{(\w+)\}", lambda m: defaults[m[1]], image)


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


# The actions that keep a job's files: in a cache, and as an artifact for
# the jobs after it. Not actions/cache/restore, which keeps nothing.
KEEPERS = ("actions/cache", "actions/upload-artifact")


def paths_kept_by(job):
    """The files each action of KEEPERS keeps for a job, by the action."""
    return {
        action: step["with"]["path"].split()
        for step in job["steps"]
        for action in KEEPERS
        if step.get("uses", "").startswith(f"{action}@")
    }


def hashed_by(key):
    """The patterns of the files a cache key hashes, by its hashFiles()."""
    return {
        pattern
        for listed in re.findall(r"hashFiles\(([^)]*)\)", key)
        for pattern in re.findall(r"""['"]([^'"]+)['"]""", listed)
    }


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
