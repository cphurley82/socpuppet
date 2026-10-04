"""Run the linters over this repository's own files.

Usage: uv run python tools/lint.py [--fix]

Lints the whole git repository the command is run in, from any directory
inside it, and exits non-zero if any linter found a problem. With --fix,
problems that can be repaired automatically are repaired in place.
"""

import argparse
import fnmatch
import os
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path

GREEN, RED, RESET = "\x1b[32m", "\x1b[31m", "\x1b[0m"


@dataclass(frozen=True)
class Linter:
    name: str
    # Which files it looks at, as globs on the path from the top of the repo.
    patterns: tuple[str, ...]
    # The command that reports problems. The files are added to the end.
    check: tuple[str, ...]
    # The command that repairs them, for a linter that can.
    fix: tuple[str, ...] | None = None


LINTERS = [
    Linter(
        "clang-format",
        patterns=("*.h", "*.cpp"),
        check=("clang-format", "--dry-run", "--Werror"),
        fix=("clang-format", "-i"),
    ),
    Linter(
        "cpplint",
        patterns=("*.h", "*.cpp"),
        check=("cpplint", "--quiet"),
    ),
    Linter(
        "ruff",
        patterns=("*.py",),
        check=("ruff", "check", "--quiet"),
    ),
]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--fix", action="store_true", help="repair what can be repaired")
    args = parser.parse_args()

    root = repo_root()
    files = repo_files(root)
    results = [run(linter, files, root, fix=args.fix) for linter in LINTERS]
    return 0 if all(results) else 1


def run(linter, files, root, fix):
    """Run one linter over the files that are its business. True if it passed."""
    files = [f for f in files if any(fnmatch.fnmatch(f, p) for p in linter.patterns)]
    if not files:
        # Given no files, a linter finds something else to read: standard
        # input, or everything under the current directory.
        return True
    program, *arguments = linter.fix if fix and linter.fix else linter.check
    result = subprocess.run(
        [tool(program), *arguments, *files],
        # From the top of the repository, where each linter's config is.
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    passed = result.returncode == 0
    report(linter.name, passed)
    print(result.stdout, end="")
    return passed


def report(linter, passed):
    """Print one line saying whether a linter passed.

    It is colored for a person at a terminal, unless they set NO_COLOR.
    """
    line = f"{'✅' if passed else '❌'} {linter}"
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        line = f"{GREEN if passed else RED}{line}{RESET}"
    print(line)


def repo_root():
    toplevel = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return Path(toplevel.stdout.strip())


def repo_files(root):
    """Every file git tracks, plus new files it has not been told to ignore.

    Paths are relative to the root. A file deleted but not yet committed is
    still tracked, so those are left out.
    """
    listing = subprocess.run(
        # -z: names come back as they are, not quoted and escaped.
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return [f for f in listing.stdout.split("\0") if (root / f).is_file()]


def tool(name):
    """The linters are installed next to the interpreter (see pyproject.toml)."""
    return str(Path(sysconfig.get_path("scripts")) / name)


if __name__ == "__main__":
    sys.exit(main())
