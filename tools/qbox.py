#!/usr/bin/env python3
"""🧦 Linux at its prompt on QBox's hart, from a checkout, in one command.

Usage:
  uv run tools/qbox.py
  uv run tools/qbox.py --jobs N

🩺 It asks the doctor first whether this machine has what socpuppet's build
and QBox's need, and stops, saying what to install, if it has not. Then it
builds QBox (tools/build_qbox.py), unless it is built already, and then
socpuppet against it, in the qbox preset's tree (build/qbox-dev).
"""

import argparse
import dataclasses
import os
import platform
import subprocess
import sys
from pathlib import Path

import build_qbox
import doctor
from needs import Failed

REPOSITORY = Path(__file__).resolve().parents[1]
#: What the one command needs of this machine, as the doctor's areas.
AREAS = ("build", "qbox")
#: The file in QBox's install that says it is built: what CMake finds QBox
#: by (cmake/Dependencies.cmake).
QBOX_PACKAGE = Path("lib/cmake/qbox-2.0/qboxConfig.cmake")


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
    root = args.root.resolve()
    if (root / "install" / QBOX_PACKAGE).is_file():
        print(
            f"🧦 QBox is built already, in {root / 'install'}. "
            f"To build it again, delete {root} first."
        )
    else:
        build_qbox.build(root, args.jobs)
    install = f"-DSOCPUPPET_QBOX_DIR={root / 'install'}"
    run("cmake", "--preset", "qbox", install)
    run("cmake", "--build", "--preset", "qbox", "--parallel", str(args.jobs))
    return 0


def run(*argv: str) -> None:
    """Run a command in the checkout, its output to the terminal."""
    if subprocess.run(argv, cwd=REPOSITORY).returncode != 0:
        raise Failed(f"{' '.join(argv)} failed")


if __name__ == "__main__":
    sys.exit(main())
