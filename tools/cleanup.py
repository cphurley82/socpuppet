#!/usr/bin/env python3
"""🧹 What is in build/, and what a build or a test left outside it.

Usage:
  uv run python tools/cleanup.py              # the report: changes nothing
  uv run python tools/cleanup.py repair       # fix what is stale in a tree
  uv run python tools/cleanup.py unused       # and remove what is unused
  uv run python tools/cleanup.py trees        # and the trees made in minutes
  uv run python tools/cleanup.py everything   # and build/qbox, build/firmware

Each tree under build/ is made by one tool of the repo, and remade by
running it again, in minutes or in hours. The report names each, its size,
what makes it and how long that takes, and the level that removes it; and
what no tool of today makes, under build/ and outside it, as unused. Each
level does what the ones before it do.
"""

import argparse
import enum
import fnmatch
import functools
import os
import shutil
import stat
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import build_qbox

REPOSITORY = Path(__file__).resolve().parents[1]


class Level(enum.Enum):
    """How much a run clears away, each level what the one before does too."""

    #: Removes nothing, but fixes what is stale inside a tree.
    REPAIR = "repair"
    UNUSED = "unused"
    TREES = "trees"
    EVERYTHING = "everything"

    def includes(self, other: "Level") -> bool:
        """Whether this level does what `other` does: being it, or after it.

        The levels are declared in the order they nest.
        """
        levels = list(Level)
        return levels.index(other) <= levels.index(self)


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


#: Where the patches are, from the top of the repository.
PATCHES = build_qbox.PATCHES.relative_to(build_qbox.REPOSITORY)

#: How the report names what repair runs in a stale checkout.
PUT_BACK_SAYS = " and ".join(
    " ".join(("git", *each)) for each in build_qbox.PUT_BACK
)


class State(enum.Enum):
    """What the report says of a thing it found."""

    #: Made by a tool of today, and as that tool left it.
    CURRENT = "current"
    #: Made by nothing of today: a tree a tool used to build in, a log, a
    #: test's leftover, an extension built for another platform.
    UNUSED = "unused"
    #: Inside a tree of today, left by something that went wrong.
    STALE = "stale"


#: How a terminal is told to color each state, and to stop.
COLORS = {
    State.CURRENT: "\033[32m",
    State.UNUSED: "\033[31m",
    State.STALE: "\033[33m",
}
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
    #: The level that removes it, or for what is stale, repairs it.
    level: Level
    #: What repairs it, if it is stale: returns what it did.
    repair: Callable[[], str] | None = field(default=None, compare=False)
    #: What repairing it costs, that the report warns of before it does.
    warning: str = ""

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
    parser.add_argument(
        "level",
        nargs="?",
        choices=[level.value for level in Level],
        help=(
            "what to do beyond the report: repair fixes what is stale, and "
            "each level after it removes more, with what the ones before do"
        ),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    found = survey(root)
    report(found)
    if args.level:
        level = Level(args.level)
        for each in found:
            if each.repair:
                print(each.repair())
        if level is Level.EVERYTHING:
            warn_of_the_cost(found)
        for each in removed_by(found, level):
            remove(root, each)
    return 0


def removed_by(found: list[Found], level: Level) -> list[Found]:
    """What `level` removes of what was found, with the levels before it."""
    # What repair fixes is inside a tree, and removed with it.
    return [
        each
        for each in found
        if each.state is not State.STALE and level.includes(each.level)
    ]


def warn_of_the_cost(found: list[Found]) -> None:
    """Say what everything removes that takes long to make again."""
    costly = [
        f"{each.path} ({each.cost} to make again)"
        for each in found
        if each.level is Level.EVERYTHING
    ]
    if costly:
        print(f"⚠️ everything removes {' and '.join(costly)}")


def remove(root: Path, found: Found) -> None:
    """Remove what was found from `root`, and say so."""
    path = root / found.path
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    print(f"🧹 removed {found.path} ({human(found.size)})")


def survey(root: Path) -> list[Found]:
    """What is in `root`'s build/, and what was left outside it."""
    return (
        owned(root)
        + stale_counters(root)
        + stale_checkouts(root)
        + unused_in_build(root)
        + outside_build(root)
    )


def owned(root: Path) -> list[Found]:
    """The trees of `root`'s build/ that the tools of today make."""
    return [
        tree.found(root) for tree in TREES if os.path.lexists(root / tree.path)
    ]


def stale_counters(root: Path) -> list[Found]:
    """The coverage counters left in the presets' trees.

    🎓 A build for coverage leaves a counter, a *.gcda, beside each object
    it runs. The coverage target deletes them all before it measures, but
    only after its build, whose test discovery runs the programs; and a
    counter an interrupted run left truncated can crash them there.
    """
    found = []
    for tree in TREES:
        if tree.made_by != PRESETS or not (root / tree.path).is_dir():
            continue
        counters = [
            Path(entry.path)
            for entry in walk(root / tree.path)
            if entry.name.endswith(".gcda")
        ]
        if counters:
            found.append(
                Found(
                    f"{tree.path}/**/*.gcda",
                    sum(map(size_of, counters)),
                    State.STALE,
                    f"{len(counters)} counter{'s' if len(counters) > 1 else ''}"
                    " of an interrupted coverage run",
                    "nothing",
                    Level.REPAIR,
                    repair=functools.partial(
                        delete_counters, tree.path, counters
                    ),
                )
            )
    return found


def delete_counters(tree: str, counters: list[Path]) -> str:
    """Delete the coverage counters of `tree`, and say so."""
    for counter in counters:
        counter.unlink()
    return f"🧹 deleted {len(counters)} *.gcda under {tree}"


def stale_checkouts(root: Path) -> list[Found]:
    """QBox's checkout, and QEMU's, where a patch of today cannot go.

    tools/build_qbox.py applies each patch of cmake/patches to its checkout
    unless it is there already. A patch changed since the last build is
    neither, and stops it.
    """
    found = []
    for each in build_qbox.CHECKOUTS:
        path = each.in_repository().as_posix()
        checkout = root / path
        if not (checkout / ".git").is_dir():
            continue
        stuck = [
            patch.name
            for patch in sorted((root / PATCHES).glob(each.glob))
            if not build_qbox.goes_in(checkout, patch)
        ]
        if stuck:
            found.append(
                Found(
                    path,
                    size_of(checkout),
                    State.STALE,
                    f"{', '.join(stuck)} neither applies nor reverses",
                    "minutes",
                    Level.REPAIR,
                    repair=functools.partial(reset, root, path),
                    warning=(
                        f"repair runs {PUT_BACK_SAYS} in {path}, "
                        "discarding uncommitted edits"
                    ),
                )
            )
    return found


def reset(root: Path, path: str) -> str:
    """Put the checkout at `path` back as its commit has it, and say so."""
    for each in build_qbox.PUT_BACK:
        subprocess.run(
            ["git", "-C", str(root / path), *each],
            stdout=subprocess.DEVNULL,
            check=True,
        )
    return f"🧹 reset {path} ({PUT_BACK_SAYS})"


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
    for each in found:
        if each.warning:
            print(f"⚠️ {each.warning}")
    print()
    totals = (
        f"{each.value} {human(freed(found, each))}"
        for each in Level
        if each is not Level.REPAIR
    )
    print(f"🧹 Each level would free: {'; '.join(totals)}.")


def freed(found: list[Found], level: Level) -> int:
    """How much `level` frees of what was found, with the levels before it."""
    return sum(each.size for each in removed_by(found, level))


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
