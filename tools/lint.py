"""Run the linters over this repository's own files.

Usage: uv run python tools/lint.py [--fix]

Lints the git repository the command is run from, and exits non-zero if any
linter found a problem. With --fix, problems that can be repaired
automatically are repaired in place.
"""

import argparse
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

GREEN, RED, RESET = "\x1b[32m", "\x1b[31m", "\x1b[0m"


def main():
    parser = argparse.ArgumentParser(description="Run the linters over this repository.")
    parser.add_argument("--fix", action="store_true", help="repair what can be repaired")
    args = parser.parse_args()

    files = [f for f in repo_files() if f.endswith((".h", ".cpp"))]
    mode = ["-i"] if args.fix else ["--dry-run", "--Werror"]
    result = subprocess.run(
        [tool("clang-format"), *mode, *files],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    report("clang-format", passed=result.returncode == 0)
    print(result.stdout, end="")
    return result.returncode


def report(linter, passed):
    """Print one line saying whether a linter passed.

    It is colored for a person at a terminal, unless they set NO_COLOR.
    """
    line = f"{'✅' if passed else '❌'} {linter}"
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        line = f"{GREEN if passed else RED}{line}{RESET}"
    print(line)


def repo_files():
    """Every file git tracks, plus new files it has not been told to ignore.

    A file deleted but not yet committed is still tracked, so those are left out.
    """
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return [f for f in listing.stdout.splitlines() if Path(f).is_file()]


def tool(name):
    """The linters are installed next to the interpreter (see pyproject.toml)."""
    return str(Path(sysconfig.get_path("scripts")) / name)


if __name__ == "__main__":
    sys.exit(main())
