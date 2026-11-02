"""Read the tree as a stranger would, and object to what is only ours.

Usage: uv run python tools/stranger.py FILE...

FILE is a path from the top of the repository, as tools/lint.py gives it.

The docs are written to be read by someone who has never met this project
or the people behind it, and two things on a page mean nothing to them:

- The name of one of our own machines or people. A page describes a
  machine by what it is instead, and a person by their role. The licence
  and the package's author are where a name belongs, and the repository's
  own URL names the account it lives under.
- A date. A page is read whenever it is read, so a date on one is a diary
  entry; the record of what happened when is the history's
  (docs/history/), the ledger's (docs/upstream.md) and the roadmap's,
  which points into the history by date.

A finding is one line, file:line:column, as the other linters print, and
the tool exits non-zero when it found anything.
"""

import re
import sys
from pathlib import Path

#: Names that mean something only to us.
NAMES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bA51\b",
        r"\bChris\b",
        r"\bHurley\b",
        r"\bcphurley82\b(?!/socpuppet)",
    )
)
NAMED = "'{}' is a name only we know; describe the machine or person instead"
#: Where a name belongs: the licence, the package's author, and this tool
#: and its tests, which have to spell what they look for.
EXCUSED = (
    "LICENSE",
    "pyproject.toml",
    "tools/stranger.py",
    "tests/tooling/test_lint_stranger.py",
)
#: A day, as the history writes one.
DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
DATED = "a date on a page is a diary entry; the history keeps the dates"
#: The pages that keep the record.
RECORD = ("docs/history/", "docs/upstream.md", "docs/roadmap.md")


def main() -> int:
    """Report every finding. Returns the exit status."""
    findings = [
        finding
        for path in map(Path, sys.argv[1:])
        for finding in findings_in(path)
    ]
    for finding in findings:
        print(finding)
    return 1 if findings else 0


def findings_in(path: Path) -> list[str]:
    """One line for each place a file says what a stranger cannot read."""
    if str(path) in EXCUSED:
        return []
    data = path.read_bytes()
    if b"\0" in data:
        return []  # An image or a binary, which nobody reads as prose.
    rules = [(name, NAMED) for name in NAMES]
    if path.suffix == ".md" and not str(path).startswith(RECORD):
        rules.append((DATE, DATED))
    text = data.decode("utf-8", errors="replace")
    return [
        f"{path}:{number}:{match.start() + 1}: {message.format(match.group())}"
        for number, line in enumerate(text.split("\n"), start=1)
        for pattern, message in rules
        for match in pattern.finditer(line)
    ]


if __name__ == "__main__":
    sys.exit(main())
