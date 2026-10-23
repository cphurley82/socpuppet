"""What a script of the repo's needs of this machine, and how it stops.

tools/build_qbox.py, tools/build_pciem.py and tools/pciem_guest.py each
need programs of this machine, and each stops before it starts, naming
the packages to install, when one is missing. The looking and the saying
are here; what each needs, and what it cannot do without them, is its own.
A script imports this as a sibling, `import needs`, which works when it is
run as a script; tools/doctor.py, which loads the scripts as modules for
their lists, puts this directory on the path first.
"""

import shutil
from collections.abc import Iterable, Sequence

#: A program or library a script needs: the name it is looked for by, the
#: Ubuntu package it comes in, and, where a Mac can do the work too, the
#: Homebrew formula.
Wanted = tuple[str, str] | tuple[str, str, str]


class Failed(Exception):
    """What stopped a script, and what to do about it."""

    @classmethod
    def without(
        cls, cannot: str, missing: Sequence[Wanted], *, see: str = ""
    ) -> "Failed":
        """`cannot` be done without `missing`, and here is how to get them.

        `cannot` is what cannot be done: "pciem cannot be built". `see` is
        where to read more, if there is somewhere.
        """
        columns = [list(each) for each in zip(*missing, strict=True)]
        names, packages = columns[0], columns[1]
        lines = [
            f"{cannot} without {' '.join(names)}.",
            f"On Ubuntu: sudo apt install {' '.join(packages)}",
        ]
        if len(columns) == 3:
            lines.append(f"On a Mac: brew install {' '.join(columns[2])}")
        if see:
            lines.append(see)
        return cls("\n".join(lines))


def not_installed(wanted: Iterable[Wanted]) -> list[Wanted]:
    """Those of `wanted` whose program is not on this machine's path."""
    return [each for each in wanted if not shutil.which(each[0])]
