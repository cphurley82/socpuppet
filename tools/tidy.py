#!/usr/bin/env python3
"""Run clang-tidy over a build tree, as the tidy target does.

Usage (cmake/DevChecks.cmake runs it):
  python tools/tidy.py --tools DIR -p TREE [--qbox INSTALL]
      [run-clang-tidy.py's options] SOURCE...

It runs the developer tools' run-clang-tidy.py with their clang-tidy, and
passes on what it says. But when clang-tidy cannot compile a source, what
it says of the sources it half-parsed is not to be trusted, so this prints
only what it could not compile, and what to do: fix the error, or, when a
header is missing, configure the tree again. A tree configured with QBox
(`--qbox`, its SOCPUPPET_QBOX_DIR) is missing its headers once QBox's
install is gone, which this says.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import build_qbox

#: How clang-tidy marks a source it could not compile.
CANNOT_COMPILE = "[clang-diagnostic-error]"
#: The developer tools' script that runs clang-tidy over each source.
RUN_CLANG_TIDY = "run-clang-tidy.py"
#: clang-tidy, which that script is told to run.
CLANG_TIDY = "clang-tidy"


def main() -> int:
    """Run clang-tidy. Returns the exit status."""
    parser = argparse.ArgumentParser(
        prog="tools/tidy.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tools",
        type=Path,
        required=True,
        help=f"where {RUN_CLANG_TIDY} and {CLANG_TIDY} are",
    )
    parser.add_argument(
        "-p", dest="tree", type=Path, required=True, help="the build tree"
    )
    parser.add_argument(
        "--qbox", type=Path, help="QBox's install, if the tree is built with it"
    )
    args, rest = parser.parse_known_args()
    ran = subprocess.run(
        [
            sys.executable,
            str(args.tools / RUN_CLANG_TIDY),
            *("-clang-tidy-binary", str(args.tools / CLANG_TIDY)),
            *("-p", str(args.tree)),
            *rest,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        # A quoted source line may hold a byte that is not UTF-8.
        text=True,
        errors="replace",
    )
    cannot = [
        line for line in ran.stdout.splitlines() if CANNOT_COMPILE in line
    ]
    if not cannot:
        print(ran.stdout, end="")
        return ran.returncode
    print("\n".join(cannot))
    print(
        "❌ clang-tidy could not compile these, so nothing else it said is "
        "to be trusted. Fix the error; or, if a header is missing, "
        f"configure the tree again ({args.tree}) with its preset."
    )
    if args.qbox and not (args.qbox / build_qbox.PACKAGE).is_file():
        print(
            f"QBox's install, {args.qbox}, is gone: uv run "
            "tools/build_qbox.py builds it again."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
