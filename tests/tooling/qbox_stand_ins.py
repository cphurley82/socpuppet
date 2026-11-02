"""Stand-ins for the programs QBox's build runs, for the tools' tests.

tools/build_qbox.py and tools/qbox.py are run for real with these on their
path. Each stand-in writes the command it was given to a log, and git's
keeps track of which patches it has applied, so a test can say what a
script asked for without fetching or building QEMU.
"""

import sys
from pathlib import Path

# A git that clones by making the directory, and applies a patch by noting
# its name: `apply --check` passes for a patch not yet applied, and
# `apply --reverse --check` for one that has been.
GIT = """
import os, sys
from pathlib import Path
args = sys.argv[1:]
tree = Path.cwd()
if args[0] == "-C":
    tree, args = Path(args[1]), args[2:]
if args[0] == "clone":
    (Path(args[-1]) / ".git").mkdir(parents=True)
elif args[:2] == ["rev-parse", "HEAD"]:
    head = tree / ".git" / "HEAD"
    print(head.read_text() if head.exists() else "0" * 40)
elif args[0] == "checkout":
    (tree / ".git" / "HEAD").write_text(args[-1])
elif args[0] == "apply":
    applied = tree / ".git" / "applied"
    done = applied.read_text().split() if applied.exists() else []
    name = os.path.basename(args[-1])
    if "--reverse" in args:
        sys.exit(0 if name in done else 1)
    if "--check" in args:
        sys.exit(1 if name in done else 0)
    applied.write_text(" ".join([*done, name]))
"""

# A cmake that, configuring, leaves QEMU's source where QBox's fetch would,
# and installing, leaves QBox's package file where its install would.
# With CONFIGURE set to "offline" it fails, having left the empty CPM.cmake
# that QBox's configure leaves when GitHub does not answer, and with "fails"
# it fails before that.
CMAKE = """
import os
from pathlib import Path
if "-B" in sys.argv:
    build = Path(sys.argv[sys.argv.index("-B") + 1])
    if os.environ.get("CONFIGURE", "") == "offline":
        (build / "cmake").mkdir(parents=True, exist_ok=True)
        (build / "cmake" / "CPM.cmake").write_text("")
    if os.environ.get("CONFIGURE", ""):
        sys.exit(1)
    (build / "_deps" / "libqemu-src" / ".git").mkdir(parents=True, exist_ok=True)
    prefix = next(
        each.split("=", 1)[1]
        for each in sys.argv
        if each.startswith("-DCMAKE_INSTALL_PREFIX=")
    )
    (build / "prefix").write_text(prefix)
if "--install" in sys.argv:
    build = Path(sys.argv[sys.argv.index("--install") + 1])
    package = Path((build / "prefix").read_text()) / "lib/cmake/qbox-2.0"
    package.mkdir(parents=True, exist_ok=True)
    (package / "qboxConfig.cmake").write_text("")
"""

# What the stand-in for pkg-config does not have, from the environment.
PKG_CONFIG = """
import os, sys
sys.exit(1 if sys.argv[-1] in os.environ.get("MISSING", "").split() else 0)
"""

#: Each stand-in by its name: those above, and the rest of what
#: tools/build_qbox.py looks for, which need do nothing.
PROGRAMS = {
    "git": GIT,
    "cmake": CMAKE,
    "pkg-config": PKG_CONFIG,
    "ninja": "",
    "meson": "",
    "bison": "",
    "flex": "",
}


def put_in(directory: Path, log: Path, programs: dict[str, str]) -> None:
    """Write each of `programs`, by name, into `directory`, logging to `log`.

    Each is a Python script that appends its command line to `log` and then
    runs its body, with `sys` imported.
    """
    logger = f"open({str(log)!r}, 'a').write(' '.join(sys.argv) + '\\n')\n"
    for name, body in programs.items():
        program = directory / name
        program.write_text(f"#!{sys.executable}\nimport sys\n{logger}{body}")
        program.chmod(0o755)


def calls(lines, program, *words):
    """The logged commands of `program` that contain every one of `words`."""
    return [
        line
        for line in lines
        if Path(line.split()[0]).name == program
        and all(word in line.split() for word in words)
    ]
