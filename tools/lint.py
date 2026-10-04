"""Run the linters over this repository's own files.

Usage: uv run python tools/lint.py [--fix]

Lints the git repository the command is run from, and exits non-zero if any
linter found a problem. With --fix, problems that can be repaired
automatically are repaired in place.
"""

import argparse
import subprocess
import sys
import sysconfig
from pathlib import Path


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
    passed = result.returncode == 0
    print(f"{'✅' if passed else '❌'} clang-format")
    print(result.stdout, end="")
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
