"""Run the linters over this repository's own files.

Usage: uv run python tools/lint.py

Lints the git repository the command is run from, and exits non-zero if any
linter found a problem.
"""

import subprocess
import sys
import sysconfig
from pathlib import Path


def main():
    files = [f for f in repo_files() if f.endswith((".h", ".cpp"))]
    result = subprocess.run([tool("clang-format"), "--dry-run", "--Werror", *files])
    return result.returncode


def repo_files():
    """Every file git tracks, plus new files it has not been told to ignore."""
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return listing.stdout.splitlines()


def tool(name):
    """The linters are installed next to the interpreter (see pyproject.toml)."""
    return str(Path(sysconfig.get_path("scripts")) / name)


if __name__ == "__main__":
    sys.exit(main())
