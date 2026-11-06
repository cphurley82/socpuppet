#!/usr/bin/env python3
"""Build QBox, Qualcomm's QEMU in SystemC, for socpuppet's qbox_cpu.

Usage:
  uv run tools/build_qbox.py                   # into build/qbox/install
  uv run tools/build_qbox.py --root DIR --jobs N

It installs QBox where `cmake --preset qbox` looks for it. QEMU is
GPL-2.0, so it is never part of the wheel: whoever wants the second hart
builds it here, from source. It takes about five minutes on 24 threads the
first time, and its tree is about 3 GB. `uv run` puts uv's CMake and Ninja
on the path. docs/setup.md lists the packages it needs.

QBox is pinned, and every change made to it, or to the QEMU it fetches, is
a patch in cmake/patches/ with an entry in docs/upstream.md. A second run
builds again what changed and applies nothing twice.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, NamedTuple

from needs import Failed, not_installed

REPOSITORY = Path(__file__).resolve().parents[1]
PATCHES = REPOSITORY / "cmake" / "patches"
#: Where QBox's source, build and install go unless asked for elsewhere,
#: from the top of the repository.
ROOT = Path("build") / "qbox"
#: Where QBox is built, from the build's root.
TREE = Path("build")
QBOX_COMMIT = "4d63017c88a147839d49028d0c60666d691460cc"  # 2026-09-24
#: The file of QBox's install that CMake finds it by (cmake/Dependencies.cmake),
#: under the install's prefix: so an install that has it is built.
PACKAGE = Path("lib/cmake/qbox-2.0/qboxConfig.cmake")
#: How many times QBox is configured before an empty CPM.cmake is taken for
#: a network that is down: GitHub sometimes answers a download with nothing
#: when it answers everything else.
CONFIGURE_TRIES = 3


class Checkout(NamedTuple):
    """A git checkout the build patches, and the patches it applies to it."""

    #: From the build's root.
    path: Path
    #: A glob over cmake/patches: the patches that go in it.
    glob: str

    def in_repository(self) -> Path:
        """Where it is from the top of the repository, at the usual root."""
        return ROOT / self.path


QBOX = Checkout(Path("src"), "qbox-*.patch")
#: QEMU's, which QBox's configure fetches into QBox's build tree.
QEMU = Checkout(TREE / "_deps" / "libqemu-src", "libqemu-*.patch")
CHECKOUTS = (QBOX, QEMU)
#: What puts a checkout back as its commit has it, discarding any edits
#: there, as git's arguments after `git -C <checkout>`. The clean, since
#: some patches add files, which a reset leaves behind.
PUT_BACK = (("reset", "--hard"), ("clean", "-fd"))

# What QBox's build stops without: each program or library, as the name it
# is looked for by, the Ubuntu package it comes in, and the Homebrew
# formula. SDL and slirp are for QEMU's configure, which asks for both
# whatever the target.
PROGRAMS = (
    ("git", "git", "git"),
    ("cmake", "cmake", "cmake"),
    ("ninja", "ninja-build", "ninja"),
    ("pkg-config", "pkg-config", "pkgconf"),
    ("meson", "meson", "meson"),
    ("bison", "bison", "bison"),
    ("flex", "flex", "flex"),
)
LIBRARIES = (
    ("glib-2.0", "libglib2.0-dev", "glib"),
    ("pixman-1", "libpixman-1-dev", "pixman"),
    ("libzip", "libzip-dev", "libzip"),
    ("libelf", "libelf-dev", "libelf"),
    ("sdl2", "libsdl2-dev", "sdl2"),
    ("slirp", "libslirp-dev", "libslirp"),
)


def main() -> int:
    """Build and install QBox. Returns the exit status."""
    parser = argparse.ArgumentParser(
        prog="tools/build_qbox.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_build_options(parser)
    args = parser.parse_args()
    # Each line is shown as it is printed, before the output of what runs
    # next, in a log as at a terminal.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    root = args.root.resolve()
    try:
        build(root, args.jobs)
    except Failed as failure:
        print(f"build_qbox.py: {failure}", file=sys.stderr)
        return 1
    if root == REPOSITORY / ROOT:
        print("Next: uv run cmake --preset qbox")
    else:
        print(
            "Next: uv run cmake --preset qbox "
            f"-DSOCPUPPET_QBOX_DIR={install_of(root)}"
        )
    return 0


def add_build_options(parser: argparse.ArgumentParser) -> None:
    """Add the options of QBox's build, `--root` and `--jobs`, to `parser`.

    For this script and for those that build QBox through it (tools/qbox.py),
    so that the two say the same.
    """
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY / ROOT,
        help="where QBox's source, build and install go (build/qbox)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="how many files a build compiles at once (default: every core)",
    )


def install_of(root: Path) -> Path:
    """Where QBox is installed, built with `root` as the build's root."""
    return root / "install"


def built(root: Path) -> bool:
    """Whether QBox is installed, built with `root` as the build's root."""
    return (install_of(root) / PACKAGE).is_file()


def build(root: Path, jobs: int) -> None:
    """Fetch QBox at its pin, patch it and QEMU, build and install them."""
    check_what_it_needs()
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    source = root / QBOX.path
    if not (source / ".git").is_dir():
        git("clone", "--quiet", "https://github.com/qualcomm/qbox", str(source))
    head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != QBOX_COMMIT:
        git("-C", str(source), "fetch", "--quiet", "origin", QBOX_COMMIT)
        git("-C", str(source), "checkout", "--quiet", "--force", QBOX_COMMIT)
    print(f"🧦 QBox at {QBOX_COMMIT[:8]}, in {source}", flush=True)
    patch(root, QBOX)

    tree = root / TREE
    install = install_of(root)
    configure(source, tree, install)
    # QEMU is fetched while QBox is configured, and built after. Its
    # patches go in between.
    patch(root, QEMU)
    command("cmake", "--build", str(tree), "--parallel", str(jobs))
    with (root / "install.log").open("w") as log:
        command("cmake", "--install", str(tree), stdout=log)

    took = round(time.monotonic() - started)
    print(f"✅ QBox is installed in {install}, in {took} s.")


def configure(source: Path, tree: Path, install: Path) -> None:
    """Configure QBox, trying again while CPM.cmake could not be fetched.

    After `CONFIGURE_TRIES` of those, say to check the network.
    """
    for attempt in range(1, CONFIGURE_TRIES + 1):
        try:
            configure_once(source, tree, install)
            return
        except Failed as failure:
            if not left_cpm_empty(tree):
                raise
            if attempt == CONFIGURE_TRIES:
                raise Failed(
                    f"{failure}\nQBox's configure could not download "
                    "CPM.cmake from GitHub, and left it empty. Check the "
                    "network with `uv run python tools/doctor.py network`, "
                    "then run this again."
                ) from failure
            print(
                "QBox's configure fetched an empty CPM.cmake; configuring "
                f"again ({attempt + 1} of {CONFIGURE_TRIES})."
            )


def left_cpm_empty(tree: Path) -> bool:
    """Whether QBox's configure left CPM.cmake empty.

    It downloads CPM.cmake from GitHub every time, and goes on with an
    empty file when it cannot (docs/upstream.md).
    """
    cpm = tree / "cmake" / "CPM.cmake"
    return cpm.exists() and cpm.stat().st_size == 0


def configure_once(source: Path, tree: Path, install: Path) -> None:
    """Configure QBox, which fetches QEMU and CPM.

    RISC-V's 64-bit QEMU only. C++20, because SystemC only links with code
    built to the same standard as itself, and socpuppet is C++20. No virgl
    and no virCL: QEMU's bundled virclrenderer does not compile against
    glibc 2.42's C11 threads, and nothing here draws. And none of QBox's
    own tests, which socpuppet does not run, and which on a Mac look for
    LLVM's tools only where Homebrew keeps them on Apple silicon.
    """
    command(
        *("cmake", "-S", str(source), "-B", str(tree), "-G", "Ninja"),
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_INSTALL_PREFIX={install}",
        "-DCPM_DOWNLOAD_ALL=ON",
        "-DBUILD_TESTING=OFF",
        "-DLIBQEMU_TARGETS=riscv64",
        "-DCMAKE_CXX_STANDARD=20",
        "-DGS_ENABLE_VIRGLRENDERER=OFF",
        "-DGS_ENABLE_VIRCLRENDERER=OFF",
    )


def check_what_it_needs() -> None:
    """Stop, naming what to install, if a program or library is missing."""
    missing = not_installed(PROGRAMS)
    if shutil.which("pkg-config"):
        missing += [
            library
            for library in LIBRARIES
            if subprocess.run(["pkg-config", "--exists", library[0]]).returncode
        ]
    if missing:
        raise Failed.without(
            "QBox cannot be built",
            missing,
            see="docs/setup.md lists every package QBox needs.",
        )


def patch(root: Path, checkout: Checkout) -> None:
    """Apply each of `checkout`'s patches to it, in the build at `root`."""
    for each in sorted(PATCHES.glob(checkout.glob)):
        apply(root / checkout.path, each)


def apply(tree: Path, patch: Path) -> None:
    """Apply a patch unless it is there already, and stop if it is neither.

    A patch that is neither was changed since `tree` was patched, and goes
    in once the checkout is put back as its commit has it.
    """
    if applies(tree, patch):
        git("-C", str(tree), "apply", str(patch))
        print(f"  patched: {patch.name}")
    elif not applies(tree, patch, reverse=True):
        raise Failed(
            f"{patch.name} does not apply to {tree}, which an older patch "
            "changed.\n"
            f"Put it back with `{put_back(tree)}`, discarding any edits of "
            f"yours there, and run this again. For {ROOT}, "
            "`uv run python tools/cleanup.py repair` does that."
        )


def put_back(tree: Path) -> str:
    """The command line that puts the checkout at `tree` back."""
    return " && ".join(
        " ".join(("git", "-C", str(tree), *each)) for each in PUT_BACK
    )


def goes_in(tree: Path, patch: Path) -> bool:
    """Whether `patch` applies to `tree`, or is applied in it already."""
    return applies(tree, patch) or applies(tree, patch, reverse=True)


def applies(tree: Path, patch: Path, *, reverse: bool = False) -> bool:
    """Whether `patch` applies to `tree`, or with `reverse`, comes out."""
    return (
        subprocess.run(
            [
                "git",
                "-C",
                str(tree),
                "apply",
                *(["--reverse"] if reverse else []),
                "--check",
                str(patch),
            ],
            capture_output=True,
        ).returncode
        == 0
    )


def git(*args: str) -> None:
    """Run git, and stop if it fails."""
    command("git", *args)


def command(*argv: str, stdout: IO[str] | None = None) -> None:
    """Run a command, its output to the terminal, and stop if it fails."""
    finished = subprocess.run(argv, stdout=stdout)
    if finished.returncode != 0:
        raise Failed(f"{' '.join(argv)} failed")


if __name__ == "__main__":
    sys.exit(main())
