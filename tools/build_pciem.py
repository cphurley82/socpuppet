#!/usr/bin/env python3
"""Build pciem's kernel module, for socpuppet's pciem_host.

Usage:
  uv run tools/build_pciem.py                  # into build/pciem
  uv run tools/build_pciem.py --root DIR --kernel DIR

🐧 pciem (https://github.com/cakehonolulu/pciem) is a Linux kernel module
that lets a program be a PCIe device on this machine's own bus: with it,
this machine's Linux is the host of the puppet's SSD. It is GPL-2.0-only,
so it is never part of the wheel: whoever wants a real host builds it
here, from source, where `cmake --preset pciem` looks for it. Building it
needs the running kernel's headers and no root. Loading it needs root and
memory set aside at boot, which docs/setup.md says how to do.

pciem is pinned. A second run builds again what changed and fetches
nothing.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
# spikes/pciem/fetch.sh pins the same commit, until the spike goes.
PCIEM_COMMIT = "f80bbb7101e180f3ed8cff3a2136e52a101f336c"  # 2026-09-30

# What pciem's build stops without: each program, and the Ubuntu package
# it comes in.
PROGRAMS = (("git", "git"), ("make", "make"))


class Failed(Exception):
    """What stopped the build, and what to do about it."""


def main() -> int:
    """Fetch pciem and build its module. Returns the exit status."""
    parser = argparse.ArgumentParser(
        prog="tools/build_pciem.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY / "build" / "pciem",
        help="where pciem's checkout and its module go (build/pciem)",
    )
    parser.add_argument(
        "--kernel",
        type=Path,
        help="the build tree of the kernel to build the module for "
        "(default: the running kernel's, /lib/modules/RELEASE/build)",
    )
    args = parser.parse_args()
    # Each line is shown as it is printed, before the output of what runs
    # next, in a log as at a terminal.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    try:
        build(args.root.resolve(), args.kernel and args.kernel.resolve())
    except Failed as failure:
        print(f"build_pciem.py: {failure}", file=sys.stderr)
        return 1
    return 0


def build(root: Path, kernel: Path | None) -> None:
    """Fetch pciem at its pin and build its module against `kernel`.

    With no `kernel`, the running kernel's build tree.
    """
    release = running_linux()
    check_programs()
    kernel = kernel_tree(kernel, release)
    if not (root / ".git").is_dir():
        git(
            "clone",
            "--quiet",
            "https://github.com/cakehonolulu/pciem.git",
            str(root),
        )
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != PCIEM_COMMIT:
        git("-C", str(root), "fetch", "--quiet", "origin", PCIEM_COMMIT)
        git("-C", str(root), "checkout", "--quiet", "--force", PCIEM_COMMIT)
    print(f"🧦 pciem at {PCIEM_COMMIT[:8]}, in {root}")
    # -Werror, as pciem's own CI builds it. Only the module: its examples
    # are other devices, and some need libraries socpuppet does not.
    command(
        "make",
        "-C",
        str(root),
        "modules",
        "KCFLAGS=-Werror",
        f"KDIR={kernel}",
    )
    print(f"✅ pciem's module is {root / 'kernel' / 'pciem.ko'}.")
    preset = "uv run cmake --preset pciem"
    if root != REPOSITORY / "build" / "pciem":
        preset += f" -DSOCPUPPET_PCIEM_DIR={root}"
    print(f"Next: load it as docs/setup.md says, then {preset}")


def running_linux() -> str:
    """The running kernel's release. Stops if this machine is not Linux."""
    system, release = subprocess.run(
        ["uname", "-sr"], capture_output=True, text=True, check=True
    ).stdout.split()
    if system != "Linux":
        raise Failed(
            f"pciem is a Linux kernel module, and this machine runs {system}. "
            "A real host is this machine's own Linux."
        )
    return release


def check_programs() -> None:
    """Stop, naming the packages to install, if a program is missing."""
    missing = [p for p in PROGRAMS if not shutil.which(p[0])]
    if missing:
        names, packages = (list(each) for each in zip(*missing, strict=True))
        raise Failed(
            f"pciem cannot be built without {' '.join(names)}.\n"
            f"On Ubuntu: sudo apt install {' '.join(packages)}"
        )


def kernel_tree(kernel: Path | None, release: str) -> Path:
    """The kernel build tree to build the module against.

    `kernel`, or with none the running kernel's, `release`'s. Stops if it
    is not one.
    """
    if kernel is not None:
        if not (kernel / "Makefile").exists():
            raise Failed(
                f"{kernel} is not a kernel build tree: it has no Makefile."
            )
        return kernel
    kernel = Path("/lib/modules") / release / "build"
    if not (kernel / "Makefile").exists():
        raise Failed(
            f"There are no headers for the running kernel, {release}, in "
            f"{kernel}.\nOn Ubuntu: sudo apt install linux-headers-{release}"
        )
    return kernel


def git(*args: str) -> None:
    """Run git, and stop if it fails."""
    command("git", *args)


def command(*argv: str) -> None:
    """Run a command, its output to the terminal, and stop if it fails."""
    if subprocess.run(argv).returncode != 0:
        raise Failed(f"{' '.join(argv)} failed")


if __name__ == "__main__":
    sys.exit(main())
