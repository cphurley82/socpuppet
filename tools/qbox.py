#!/usr/bin/env python3
"""🧦 Linux at its prompt on QBox's hart, from a checkout, in one command.

Usage:
  uv run tools/qbox.py

🩺 It asks the doctor first whether this machine has what socpuppet's build
and QBox's need, and stops, saying what to install, if it has not.
"""

import argparse
import dataclasses
import platform
import sys
from pathlib import Path

import doctor

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
    parser.parse_args()
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
