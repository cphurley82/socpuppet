"""tools/nightly_gate.py: whether the scheduled nightly has anything to do."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
TOOL = REPOSITORY / "tools" / "nightly_gate.py"

COMMIT = "c0ffee"
OTHER = 999


@pytest.fixture
def gh(tmp_path_factory):
    """A `gh` on a PATH of its own, that knows only the runs a test gives it.

    Like GitHub's, its `run list` answers with the runs of the workflow and
    the commit it is asked about, and no others.
    """
    home = tmp_path_factory.mktemp("gh")
    (home / "runs.json").write_text("[]\n")
    program = home / "gh"
    program.write_text(
        f"""#!{sys.executable}
import json, sys
from pathlib import Path

home = Path({str(home)!r})
if (home / "broken").exists():
    sys.exit("gh: no route to GitHub")
if (home / "babbling").exists():
    print("Welcome to a new version of gh!")
    sys.exit(0)
asked = sys.argv[1:]
workflow = asked[asked.index("--workflow") + 1]
commit = asked[asked.index("--commit") + 1]
runs = json.loads((home / "runs.json").read_text())
print(json.dumps([
    run["run"] for run in runs
    if run["workflow"] == workflow and run["commit"] == commit
]))
"""
    )
    program.chmod(0o755)
    return home


def the_nightly_has_run(gh, *runs):
    (gh / "runs.json").write_text(json.dumps(runs))


def a_run(
    number,
    *,
    event="workflow_dispatch",
    status="completed",
    conclusion="success",
    hours_ago=2,
    commit=COMMIT,
    workflow="nightly.yml",
):
    """A run of a workflow, as `gh run list` describes it."""
    created = datetime.now(UTC) - timedelta(hours=hours_ago)
    return {
        "commit": commit,
        "workflow": workflow,
        "run": {
            "databaseId": number,
            "event": event,
            "status": status,
            "conclusion": conclusion if status == "completed" else "",
            "createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }


def gh_cannot_reach_github(gh):
    (gh / "broken").touch()


def gh_answers_with_something_other_than_runs(gh):
    (gh / "babbling").touch()


def gate(gh, event="schedule"):
    return subprocess.run(
        [sys.executable, TOOL],
        env={
            **os.environ,
            "GITHUB_EVENT_NAME": event,
            "GITHUB_SHA": COMMIT,
            "PATH": f"{gh}{os.pathsep}{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
    )


def test_a_run_by_hand_runs_a_commit_another_run_by_hand_passed(gh):
    the_nightly_has_run(gh, a_run(OTHER))

    assert gate(gh, event="workflow_dispatch").stdout == "run=true\n"


def test_a_scheduled_run_skips_a_commit_a_run_by_hand_passed_and_names_it(gh):
    the_nightly_has_run(gh, a_run(OTHER, conclusion="success"))

    answer = gate(gh)

    assert answer.stdout == "run=false\n"
    assert str(OTHER) in answer.stderr


def test_a_scheduled_run_runs_a_commit_a_run_by_hand_failed_and_names_it(gh):
    the_nightly_has_run(gh, a_run(OTHER, conclusion="failure"))

    answer = gate(gh)

    assert answer.stdout == "run=true\n"
    assert str(OTHER) in answer.stderr


@pytest.mark.parametrize("status", ["in_progress", "queued"])
def test_a_scheduled_run_skips_a_commit_a_run_by_hand_is_still_on(gh, status):
    the_nightly_has_run(gh, a_run(OTHER, status=status))

    assert gate(gh).stdout == "run=false\n"


def test_a_scheduled_run_runs_a_commit_no_other_run_has(gh):
    assert gate(gh).stdout == "run=true\n"


def test_a_scheduled_run_runs_a_commit_only_the_schedule_has_run(gh):
    the_nightly_has_run(gh, a_run(OTHER, event="schedule"))

    assert gate(gh).stdout == "run=true\n"


@pytest.mark.parametrize(
    "conclusion",
    ["timed_out", "cancelled", "action_required", "startup_failure"],
)
def test_a_scheduled_run_runs_a_commit_whose_other_run_did_not_pass(
    gh, conclusion
):
    the_nightly_has_run(gh, a_run(OTHER, conclusion=conclusion))

    assert gate(gh).stdout == "run=true\n"


def test_a_scheduled_run_runs_a_commit_whose_other_run_was_yesterday(gh):
    the_nightly_has_run(gh, a_run(OTHER, hours_ago=25))

    assert gate(gh).stdout == "run=true\n"


def test_a_scheduled_run_runs_a_commit_when_another_commit_was_run(gh):
    the_nightly_has_run(gh, a_run(OTHER, commit="decade"))

    assert gate(gh).stdout == "run=true\n"


def test_a_scheduled_run_runs_a_commit_another_workflow_ran(gh):
    the_nightly_has_run(gh, a_run(OTHER, workflow="ci.yml"))

    assert gate(gh).stdout == "run=true\n"


def test_when_gh_fails_a_scheduled_run_warns_and_runs(gh):
    the_nightly_has_run(gh, a_run(OTHER))
    gh_cannot_reach_github(gh)

    answer = gate(gh)

    assert answer.stdout == "run=true\n"
    assert answer.stderr.startswith("::warning::")
    assert "no route to GitHub" in answer.stderr
    assert answer.returncode == 0


def test_when_the_gate_itself_breaks_a_scheduled_run_warns_and_runs(gh):
    the_nightly_has_run(gh, a_run(OTHER))
    gh_answers_with_something_other_than_runs(gh)

    answer = gate(gh)

    assert answer.stdout == "run=true\n"
    assert answer.stderr.startswith("::warning::")
    assert answer.returncode == 0


def test_the_gate_run_outside_github_says_it_runs_rather_than_crashing(gh):
    answer = subprocess.run(
        [sys.executable, TOOL],
        env={
            name: value
            for name, value in os.environ.items()
            if not name.startswith("GITHUB_")
        },
        capture_output=True,
        text=True,
    )

    assert answer.stdout == "run=true\n"
    assert answer.returncode == 0
