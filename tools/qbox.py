#!/usr/bin/env python3
"""🧦 Linux at its prompt on QBox's hart, from a checkout, in one command.

Usage:
  uv run tools/qbox.py
  uv run tools/qbox.py --jobs N

🩺 It asks the doctor first whether this machine has what socpuppet's build
and QBox's need, and stops, saying what to install, if it has not. Then it
builds QBox (tools/build_qbox.py), unless it is built already, and then
socpuppet against it, in the qbox preset's tree (build/qbox-dev). And then
it hands this terminal to 🐧 Linux on QBox's hart, as `socpuppet linux
--cpu qbox_cpu`: what is typed, or piped in, goes to Linux's shell, Ctrl-]
leaves, and the command ends as that does.
"""

import argparse
import dataclasses
import os
import platform
import sys
from pathlib import Path

import build_qbox
import doctor
from needs import Failed

REPOSITORY = Path(__file__).resolve().parents[1]
#: What the one command needs of this machine, as the doctor's areas.
AREAS = ("build", "qbox")


def main() -> int:
    """Take the checkout to Linux's prompt. Returns the exit status."""
    parser = argparse.ArgumentParser(
        prog="tools/qbox.py",
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
        help="how many files each build compiles at once (default: every core)",
    )
    args = parser.parse_args()
    missing = [
        report
        for report in doctor.examine(
            # Optional to the doctor, as few need QBox; not here.
            [
                dataclasses.replace(area, optional=False)
                for area in doctor.AREAS
                if area.name in AREAS
            ],
            platform.system(),
        )
        if report.problems
    ]
    if missing:
        print("🩺 This machine is missing what QBox's hart needs:")
        for report in missing:
            print(report.show())
        print("Install it, then run this again.")
        return 1
    # Each line is shown as it is printed, before the output of what runs
    # next, in a log as at a terminal.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    # A --root relative to where this was run, then the checkout, where the
    # presets and the images are.
    root = args.root.resolve()
    os.chdir(REPOSITORY)
    try:
        build(root, args.jobs)
    except Failed as failure:
        print(f"tools/qbox.py: {failure}", file=sys.stderr)
        return 1
    boot_linux()
    return 0


def build(root: Path, jobs: int) -> None:
    """Build QBox into `root`, unless it is there, then socpuppet with it."""
    install = build_qbox.install_of(root)
    if build_qbox.built(root):
        print(
            f"🧦 QBox is built already, in {install}. To bring it up to date "
            "with its pin and its patches, which builds only what changed: "
            f"uv run tools/build_qbox.py --root {root}"
        )
    else:
        build_qbox.build(root, jobs)
    build_qbox.command(
        "cmake", "--preset", "qbox", f"-DSOCPUPPET_QBOX_DIR={install}"
    )
    build_qbox.command(
        "cmake", "--build", "--preset", "qbox", "--parallel", str(jobs)
    )


def boot_linux() -> None:
    """Become `socpuppet linux` on QBox's hart, in the checkout.

    The checkout's socpuppet, as the qbox tree built it, and the checkout's
    images if it has built them, or else those fetched into the cache.
    """
    # What was printed goes first: nothing of this process is left after.
    sys.stdout.flush()
    os.execvpe(
        "uv",
        [
            *("uv", "run", "python", "-m", "socpuppet"),
            *("linux", "--cpu", "qbox_cpu"),
        ],
        {**os.environ, "PYTHONPATH": str(REPOSITORY / "python")},
    )


if __name__ == "__main__":
    sys.exit(main())
