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
from typing import IO

from needs import Failed, not_installed

REPOSITORY = Path(__file__).resolve().parents[1]
PATCHES = REPOSITORY / "cmake" / "patches"
QBOX_COMMIT = "4d63017c88a147839d49028d0c60666d691460cc"  # 2026-09-24

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
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY / "build" / "qbox",
        help="where QBox's source, build and install go (build/qbox)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="how many files to compile at once (default: every core)",
    )
    args = parser.parse_args()
    # Each line is shown as it is printed, before the output of what runs
    # next, in a log as at a terminal.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    try:
        build(args.root.resolve(), args.jobs)
    except Failed as failure:
        print(f"build_qbox.py: {failure}", file=sys.stderr)
        return 1
    return 0


def build(root: Path, jobs: int) -> None:
    """Fetch QBox at its pin, patch it and QEMU, build and install them."""
    check_what_it_needs()
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    source = root / "src"
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
    for patch in sorted(PATCHES.glob("qbox-*.patch")):
        apply(source, patch, root)

    tree = root / "build"
    install = root / "install"
    configure(source, tree, install)
    # QEMU is fetched while QBox is configured, and built after. Its
    # patches go in between.
    for patch in sorted(PATCHES.glob("libqemu-*.patch")):
        apply(tree / "_deps" / "libqemu-src", patch, root)
    command("cmake", "--build", str(tree), "--parallel", str(jobs))
    with (root / "install.log").open("w") as log:
        command("cmake", "--install", str(tree), stdout=log)

    took = round(time.monotonic() - started)
    print(f"✅ QBox is installed in {install}, in {took} s.")
    if root == REPOSITORY / "build" / "qbox":
        print("Next: uv run cmake --preset qbox")
    else:
        print(
            f"Next: uv run cmake --preset qbox -DSOCPUPPET_QBOX_DIR={install}"
        )


def configure(source: Path, tree: Path, install: Path) -> None:
    """Configure QBox, which fetches QEMU, and say so if CPM could not be.

    RISC-V's 64-bit QEMU only. C++20, because SystemC only links with code
    built to the same standard as itself, and socpuppet is C++20. No virgl
    and no virCL: QEMU's bundled virclrenderer does not compile against
    glibc 2.42's C11 threads, and nothing here draws. And none of QBox's
    own tests, which socpuppet does not run, and which on a Mac look for
    LLVM's tools only where Homebrew keeps them on Apple silicon.
    """
    try:
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
    except Failed as failure:
        # QBox's configure downloads CPM.cmake from GitHub every time, and
        # goes on with an empty file when it cannot (docs/upstream.md).
        cpm = tree / "cmake" / "CPM.cmake"
        if cpm.exists() and cpm.stat().st_size == 0:
            raise Failed(
                f"{failure}\nQBox's configure could not download CPM.cmake "
                "from GitHub, and left it empty. Check the network with "
                "`uv run python tools/doctor.py network`, then run this again."
            ) from failure
        raise


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


def apply(tree: Path, patch: Path, root: Path) -> None:
    """Apply a patch unless it is there already, and stop if it is neither.

    `root` is the build's, which a patch that is neither is fixed by
    deleting.
    """
    git_apply = ["git", "-C", str(tree), "apply"]
    if (
        subprocess.run(
            [*git_apply, "--check", str(patch)], capture_output=True
        ).returncode
        == 0
    ):
        git("-C", str(tree), "apply", str(patch))
        print(f"  patched: {patch.name}")
    elif subprocess.run(
        [*git_apply, "--reverse", "--check", str(patch)], capture_output=True
    ).returncode:
        raise Failed(
            f"{patch.name} does not apply to {tree}.\n"
            f"Delete {root} and run this again."
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
