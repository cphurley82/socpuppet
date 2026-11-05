"""Whether the scheduled nightly has anything to do tonight.

Usage: uv run python tools/nightly_gate.py >> "$GITHUB_OUTPUT"

GitHub starts a scheduled run hours late, so the night's run is started by
hand in the evening, and the scheduled one comes along after it to the same
commit (docs/ci.md). This prints `run=false` when a run of the nightly by
hand took this commit in the last day and passed, or is still going, and
`run=true` otherwise: a run by hand that failed, timed out, was cancelled or
never started leaves tonight's run to try again. The reason goes to stderr,
for whoever reads the log. A run by hand always runs.
The nightly's first job runs this, and every other job waits for its answer
(.github/workflows/nightly.yml).

💡 If GitHub cannot be asked, or anything else goes wrong here, the answer
is to run, with a warning: a gate that is broken must not quietly stop the
nightly.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

#: How long a run of a commit answers for it.
RECENTLY = timedelta(hours=24)


def main() -> None:
    """Say `run=true` or `run=false` for GitHub, and why for a person."""
    try:
        run, why = verdict()
    except Exception as broke:
        run = True
        why = f"::warning::The gate broke ({broke!r}), so the nightly runs."
    print(why, file=sys.stderr)
    print(f"run={str(run).lower()}")


def verdict() -> tuple[bool, str]:
    """Whether tonight's run has anything to do, and why."""
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return True, "🌙 A run by hand always runs."
    asked = subprocess.run(
        [
            "gh", "run", "list",
            "--workflow", "nightly.yml",
            "--commit", os.environ["GITHUB_SHA"],
            "--json", "databaseId,event,status,conclusion,createdAt",
        ],
        capture_output=True,
        text=True,
    )  # fmt: skip
    if asked.returncode != 0:
        why = " ".join(asked.stderr.split())
        return (
            True,
            f"::warning::Could not ask GitHub for this commit's runs ({why}), "
            "so the nightly runs.",
        )
    for run in json.loads(asked.stdout):
        age = datetime.now(UTC) - datetime.fromisoformat(run["createdAt"])
        # 💡 Only a run by hand counts: a scheduled run that skipped ends
        # green too, and counting it would skip every quiet night after.
        if run["event"] != "workflow_dispatch" or age > RECENTLY:
            continue
        hours = f"{age.total_seconds() / 3600:.1f} hours ago"
        still_going = run["status"] != "completed"
        if run["conclusion"] == "success" or still_going:
            outcome = "still going" if still_going else "passed"
            return (
                False,
                f"🌙 Run {run['databaseId']}, by hand, took this commit "
                f"{hours} ({outcome}), so there is nothing to do tonight.",
            )
        return (
            True,
            f"🌙 Run {run['databaseId']}, by hand, took this commit {hours} "
            f"and ended {run['conclusion'].replace('_', ' ')}, so tonight "
            "tries again.",
        )
    return True, "🌙 No run by hand has passed this commit in the last day."


if __name__ == "__main__":
    main()
