#!/usr/bin/env python3
"""🧹 What is in build/, and what a build or a test left outside it.

Usage:
  uv run python tools/cleanup.py          # the report: changes nothing

Each tree under build/ is made by one tool of the repo, and remade by
running it again, in minutes or in hours. The report names each, its size,
what makes it and how long that takes, and the level that removes it; and
what no tool of today makes, under build/ and outside it, as unused.
"""

import argparse
import enum
import fnmatch
import os
import stat
import subprocess
import sys
import sysconfig
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


class Level(enum.Enum):
    """How much a run clears away, each level what the one before does too."""

    UNUSED = "unused"
    TREES = "trees"
    EVERYTHING = "everything"


@dataclass(frozen=True)
class Tree:
    """A tree under build/ that a tool of the repo makes, and remakes."""

    #: From the top of the repository.
    path: str
    #: What makes it.
    made_by: str
    #: How long it takes to make again.
    cost: str
    #: The level that removes it.
    level: Level

    def found(self, root: Path) -> "Found":
        """What the report says of it, in `root`."""
        return Found(
            self.path,
            size_of(root / self.path),
            State.CURRENT,
            self.made_by,
            self.cost,
            self.level,
        )


PRESETS = "the presets (CMakePresets.json)"
DEVCONTAINER = "tools/devcontainer.py"
CI = "tools/ci.py"

TREES = (
    Tree("build/dev", PRESETS, "minutes", Level.TREES),
    Tree("build/linux", PRESETS, "minutes", Level.TREES),
    Tree("build/qbox-dev", PRESETS, "minutes", Level.TREES),
    Tree("build/pciem-dev", PRESETS, "minutes", Level.TREES),
    Tree("build/pciem", "tools/build_pciem.py", "minutes", Level.TREES),
    Tree("build/twister", "firmware/twister.py", "minutes", Level.TREES),
    Tree("build/container", DEVCONTAINER, "tens of minutes", Level.TREES),
    Tree("build/linux-venv", DEVCONTAINER, "minutes", Level.TREES),
    Tree("build/linux-python", DEVCONTAINER, "minutes", Level.TREES),
    Tree("build/linux-uv-cache", DEVCONTAINER, "minutes", Level.TREES),
    Tree("build/ci", CI, "nothing: its logs", Level.TREES),
    Tree("build/wheelhouse", CI, "minutes", Level.TREES),
    Tree("build/sdist", CI, "minutes", Level.TREES),
    Tree("build/ccache", CI, "a slower wheel build", Level.TREES),
    Tree("build/wheel", "uv build (pyproject.toml)", "minutes", Level.TREES),
    Tree("build/tap", "tools/tap.py", "minutes", Level.TREES),
    Tree("build/images", "tools/released_images.py", "minutes", Level.TREES),
    Tree(
        "build/qbox", "tools/build_qbox.py", "about an hour", Level.EVERYTHING
    ),
    Tree("build/firmware", "firmware/build.py", "hours", Level.EVERYTHING),
)


#: What a run of the tests or of an example leaves outside build/, which git
#: ignores and nothing reads again, by the name of the file or directory.
LEFTOVERS = (
    ".coverage",
    ".coverage.*",
    "dist",
    "wheelhouse",
    "*.egg-info",
    "*.pcap",
)


#: The extension a build copies into the package, for each platform it was
#: built for, and this platform's.
EXTENSIONS = "python/socpuppet/_core.*.so"
EXTENSION = Tree(
    f"python/socpuppet/_core{sysconfig.get_config_var('EXT_SUFFIX')}",
    PRESETS,
    "minutes",
    Level.TREES,
)


class State(enum.Enum):
    """What the report says of a thing it found."""

    #: Made by a tool of today, and as that tool left it.
    CURRENT = "current"
    #: Made by nothing of today: a tree a tool used to build in, a log, a
    #: test's leftover, an extension built for another platform.
    UNUSED = "unused"


#: How a terminal is told to color each state, and to stop.
COLORS = {State.CURRENT: "\033[32m", State.UNUSED: "\033[31m"}
RESET = "\033[0m"

#: How each column of the report is aligned: the size to the right.
ALIGN = ("<", "<", ">", "<", "<", "<")


@dataclass(frozen=True)
class Found:
    """Something the report names, and what it says of it."""

    path: str
    size: int
    state: State
    made_by: str
    cost: str
    #: The level that removes it.
    level: Level

    def row(self) -> tuple[str, ...]:
        """Its columns in the report."""
        return (
            self.state.value,
            self.path,
            human(self.size),
            self.made_by,
            self.cost,
            self.level.value,
        )


def main() -> int:
    """Report what is in build/, and left outside it. Returns the status."""
    parser = argparse.ArgumentParser(
        prog="tools/cleanup.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # The repository to look in, for the tests.
    parser.add_argument(
        "--root", type=Path, default=REPOSITORY, help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    report(survey(args.root.resolve()))
    return 0


def survey(root: Path) -> list[Found]:
    """What is in `root`'s build/, and what was left outside it."""
    return owned(root) + unused_in_build(root) + outside_build(root)


def owned(root: Path) -> list[Found]:
    """The trees of `root`'s build/ that the tools of today make."""
    return [
        tree.found(root) for tree in TREES if os.path.lexists(root / tree.path)
    ]


def unused_in_build(root: Path) -> list[Found]:
    """What is in `root`'s build/ that no tool of today makes."""
    build = root / "build"
    if not build.is_dir():
        return []
    paths = {tree.path for tree in TREES}
    return [
        found_unused(root, path)
        for path in sorted(f"build/{name}" for name in os.listdir(build))
        if path not in paths
    ]


def outside_build(root: Path) -> list[Found]:
    """What a build or a test left in `root`, outside build/.

    The extension a build copies into the package is current if it was
    built for this platform, and unused if for another. A leftover is
    unused. The rest that git ignores, the virtual environment and the
    caches, it leaves alone.
    """
    found = []
    for path in ignored(root):
        if path == EXTENSION.path:
            found.append(EXTENSION.found(root))
        elif fnmatch.fnmatchcase(path, EXTENSIONS):
            found.append(
                found_unused(root, path, "a build for another platform")
            )
        elif any(
            fnmatch.fnmatchcase(Path(path).name, each) for each in LEFTOVERS
        ):
            found.append(found_unused(root, path, "a leftover outside build/"))
    return found


def ignored(root: Path) -> list[str]:
    """What git ignores in `root` outside build/, a directory as one entry.

    Only what git ignores, so that nothing of the repository's own is ever
    named.
    """
    listed = subprocess.run(
        [
            *("git", "-C", str(root), "ls-files", "-z"),
            *("--others", "--ignored", "--exclude-standard", "--directory"),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(
        path.rstrip("/")
        for path in listed.split("\0")
        if path and not path.startswith("build/")
    )


def found_unused(
    root: Path, path: str, made_by: str = "no tool of today"
) -> Found:
    """What the report says of `path` in `root`, which nothing today makes."""
    return Found(
        path,
        size_of(root / path),
        State.UNUSED,
        made_by,
        "nothing",
        Level.UNUSED,
    )


def report(found: list[Found]) -> None:
    """Print a line for each thing found, in columns."""
    if not found:
        print("✨ Nothing to clean: build/ is empty, and nothing is left over.")
        return
    rows = [each.row() for each in found]
    widths = [max(map(len, column)) for column in zip(*rows, strict=True)]
    for each, row in zip(found, rows, strict=True):
        cells = [
            f"{cell:{align}{width}}"
            for cell, align, width in zip(row, ALIGN, widths, strict=True)
        ]
        # Painted once padded, so that the color takes no room in a column.
        cells[0] = paint(cells[0], each.state)
        print("  ".join(cells).rstrip())
    print()
    totals = (f"{each.value} {human(freed(found, each))}" for each in Level)
    print(f"🧹 Each level would free: {'; '.join(totals)}.")


def freed(found: list[Found], level: Level) -> int:
    """How much `level` frees of what was found, with the levels before it.

    Level is declared in the order the levels nest.
    """
    levels = list(Level)
    return sum(
        each.size
        for each in found
        if levels.index(each.level) <= levels.index(level)
    )


def paint(text: str, state: State) -> str:
    """Color `text` as `state` is colored, for a person at a terminal.

    Plain when the output is not a terminal, or the person set NO_COLOR.
    """
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{COLORS[state]}{text}{RESET}"


def size_of(path: Path) -> int:
    """How much of the disk `path` takes, in bytes, as `du` counts it.

    A symlink is counted as itself, never as what it points at.
    """
    top = path.stat(follow_symlinks=False)
    blocks = top.st_blocks
    if stat.S_ISDIR(top.st_mode):
        blocks += sum(
            entry.stat(follow_symlinks=False).st_blocks for entry in walk(path)
        )
    return blocks * 512


def walk(path: Path) -> Iterator[os.DirEntry[str]]:
    """Every file and directory under `path`, following no symlink."""
    with os.scandir(path) as entries:
        for entry in entries:
            yield entry
            if entry.is_dir(follow_symlinks=False):
                yield from walk(Path(entry.path))


def human(size: int) -> str:
    """A size in bytes as a person reads it: `3.0 MB`, in powers of 1024."""
    amount, unit = float(size), "B"
    for larger in ("KB", "MB", "GB", "TB"):
        if amount < 1024:
            break
        amount, unit = amount / 1024, larger
    return f"{amount:.1f} {unit}"


if __name__ == "__main__":
    sys.exit(main())
