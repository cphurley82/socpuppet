"""Hold everything that is generated from the register maps to them.

Usage: uv run python tools/regs.py check FILE...

🎓 A register map says what a block's registers are: where each one is,
which bits of it mean what, and what firmware may do to them. They are
written once, in SystemRDL (the files in regs/), which is the language
the industry writes them in.

`check` compiles each file named, and exits non-zero if one does not
compile. tools/lint.py runs it.
"""

import argparse
import sys

from systemrdl import RDLCompileError, RDLCompiler


def main():
    """Check the register maps named. Returns the exit status."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["check"])
    parser.add_argument("files", nargs="+", metavar="FILE")
    args = parser.parse_args()

    status = 0
    for file in args.files:
        try:
            RDLCompiler().compile_file(file)
        except RDLCompileError:
            # The compiler has said what is wrong, and where.
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
