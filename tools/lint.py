"""Run the linters over this repository's own files.

Usage: uv run python tools/lint.py [--fix] [linter ...]

Lints the whole git repository the command is run in, from any directory
inside it, and exits non-zero if any linter found a problem. With --fix,
problems that can be repaired automatically are repaired in place. Name one
or more linters to run only those.
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

# Where this file is, and the repo's other tools with it.
TOOLS = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Linter:
    """One linter: what it is called, which files it checks, and how."""

    name: str
    # Which files it looks at, as globs on the path from the top of the repo.
    # A * matches / too, so "*.h" is every header at any depth.
    patterns: tuple[str, ...]
    # The command that reports problems. The files are added to the end.
    check: tuple[str, ...]
    # The command that repairs them, for a linter that can.
    fix: tuple[str, ...] | None = None


# In the order they run. A linter that repairs files comes before the ones
# that only check the same files, so that --fix leaves them something clean.
LINTERS = [
    Linter(
        "systemrdl",
        # The register maps (tools/regs.py). It comes first because what
        # is generated from them is C, Python and Markdown, which the
        # linters after it then check. A file that --fix makes for the
        # first time they see on the next run: the files are listed once,
        # before any linter has run.
        patterns=("regs/*.rdl",),
        check=("python", str(TOOLS / "regs.py"), "check"),
        fix=("python", str(TOOLS / "regs.py"), "write"),
    ),
    Linter(
        "clang-format",
        # C++, and the C that is written for Zephyr, which has a style of
        # its own: a .clang-format in a directory speaks for what is under
        # it.
        patterns=("*.h", "*.cpp", "*.c"),
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
        fix=("ruff", "check", "--quiet", "--fix"),
    ),
    Linter(
        "ruff-format",
        patterns=("*.py",),
        check=("ruff", "format", "--quiet", "--check"),
        fix=("ruff", "format", "--quiet"),
    ),
    Linter(
        "mypy",
        # The package, where a wrong type would reach a user.
        patterns=("python/*.py",),
        check=("mypy", "--no-error-summary"),
    ),
    Linter(
        "address-map",
        # The tables in the page are generated from the board descriptions
        # (tools/address_map_docs.py). It comes before rumdl, which then
        # checks what was written.
        patterns=("docs/address-map.md",),
        check=("python", str(TOOLS / "address_map_docs.py"), "check"),
        fix=("python", str(TOOLS / "address_map_docs.py"), "write"),
    ),
    Linter(
        "rumdl",
        patterns=("*.md",),
        check=("rumdl", "check", "--quiet", "--no-cache"),
        fix=("rumdl", "check", "--quiet", "--no-cache", "--fix"),
    ),
    Linter(
        "actionlint",
        patterns=(".github/workflows/*.yml", ".github/workflows/*.yaml"),
        check=("actionlint",),
    ),
    Linter(
        "shellcheck",
        patterns=("*.sh",),
        # gcc format: one line per finding, starting file:line:column.
        check=("shellcheck", "--format=gcc"),
    ),
]


def main():
    """Run the linters asked for. Returns the exit status."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fix", action="store_true", help="repair what can be repaired"
    )
    parser.add_argument(
        "linters",
        nargs="*",
        choices=[linter.name for linter in LINTERS],
        metavar="linter",
        help="run only these (default: all of them): %(choices)s",
    )
    args = parser.parse_args()

    root = repo_root()
    files = repo_files(root)
    results = [
        run(linter, files, root, fix=args.fix)
        for linter in LINTERS
        if not args.linters or linter.name in args.linters
    ]
    return 0 if all(results) else 1


def run(linter, files, root, fix):
    """Run one linter over the files that are its business.

    Returns True if it passed.
    """
    files = [
        f for f in files if any(fnmatch.fnmatch(f, p) for p in linter.patterns)
    ]
    if not files:
        # Given no files, a linter finds something else to read: standard
        # input, or everything under the current directory.
        return True
    program, *arguments = linter.fix if fix and linter.fix else linter.check
    try:
        result = subprocess.run(
            [tool(program), *arguments, *files],
            # From the top of the repository, where each linter's config is.
            cwd=root,
            # A linter may call another: actionlint runs shellcheck on the
            # scripts inside a workflow, and looks for it on the PATH.
            env={
                **os.environ,
                "PATH": tools_directory() + os.pathsep + os.environ["PATH"],
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        sys.exit(
            f"{program} is not installed next to {sys.executable}. "
            "Run `uv sync` to install the linters, then run this as "
            "`uv run python tools/lint.py`."
        )
    passed = result.returncode == 0
    report(linter.name, passed)
    print(result.stdout, end="")
    return passed


def report(name, passed):
    """Print one line saying whether a linter passed.

    It is colored for a person at a terminal, unless they set NO_COLOR.
    """
    line = f"{'✅' if passed else '❌'} {name}"
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        line = f"{GREEN if passed else RED}{line}{RESET}"
    print(line)


def repo_root():
    """The top of the git repository the command was run in."""
    toplevel = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if toplevel.returncode != 0:
        sys.exit(
            f"git could not find the repository: {toplevel.stderr.strip()}\n"
            f"Lint finds its files by asking git, and {Path.cwd()} is not "
            "inside a git repository that git will read. Run lint from "
            "inside your socpuppet checkout."
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
    """The path of a linter's program."""
    return str(Path(tools_directory()) / name)


def tools_directory():
    """Where the linters are: next to the interpreter (see pyproject.toml)."""
    return sysconfig.get_path("scripts")


if __name__ == "__main__":
    sys.exit(main())
