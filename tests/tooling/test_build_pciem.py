"""tools/build_pciem.py, which builds pciem's kernel module for PciemHost.

The script is run for real, with stand-ins for git, make and uname on its
path. Each stand-in writes the command it was given to a log, so the tests
can say what the script asked for without fetching pciem or building a
kernel module.
"""

import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "build_pciem.py"


def _tool():
    if str(SCRIPT.parent) not in sys.path:  # for its sibling, tools/needs.py
        sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("build_pciem", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The commit pciem is pinned to, as the tool says.
PIN = _tool().PCIEM_COMMIT

# A git that clones by making the directory, and checks out by noting the
# commit as HEAD.
GIT = """
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
"""

# A uname that says what the environment says: the system, then the
# kernel's release.
UNAME = """
import os
print(os.environ["SYSTEM"], os.environ["RELEASE"])
"""


@dataclass
class Machine:
    """A machine of stand-ins to run the script on.

    `kernel` is a kernel build tree, which the script is given unless a
    test says otherwise, and `root` is where the script is told to put
    pciem.
    """

    bin: Path
    log: Path
    kernel: Path
    root: Path

    def run(
        self,
        *args: str,
        kernel: Path | None = None,
        system: str = "Linux",
        release: str = "7.0.0-38-generic",
        missing: frozenset[str] = frozenset(),
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        """Run the script; returns its result and the commands it ran."""
        for program in missing:
            (self.bin / program).unlink()
        kernel_option = [] if kernel is None else ["--kernel", str(kernel)]
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(self.root),
                *kernel_option,
                *args,
            ],
            env={
                **os.environ,
                "PATH": str(self.bin),
                "SYSTEM": system,
                "RELEASE": release,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return result, lines


@pytest.fixture
def machine(tmp_path):
    """A machine of stand-ins, with a kernel build tree."""
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = tmp_path / "log"
    logger = f"open({str(log)!r}, 'a').write(' '.join(sys.argv) + '\\n')\n"
    for name, body in {"git": GIT, "make": "", "uname": UNAME}.items():
        program = bin_directory / name
        program.write_text(f"#!{sys.executable}\nimport sys\n{logger}{body}")
        program.chmod(0o755)
    kernel = tmp_path / "kernel"
    kernel.mkdir()
    (kernel / "Makefile").write_text("")
    return Machine(bin_directory, log, kernel, tmp_path / "pciem")


def test_a_first_run_checks_pciem_out_at_its_pin_and_builds_only_its_module_with_werror(
    machine,
):
    result, lines = machine.run(kernel=machine.kernel)

    assert result.returncode == 0, result.stdout
    assert calls(lines, "git", "checkout", PIN)
    assert calls(
        lines,
        "make",
        "modules",
        "KCFLAGS=-Werror",
        f"KDIR={machine.kernel}",
    )


def test_after_a_build_it_says_to_configure_with_the_pciem_preset(machine):
    result, _ = machine.run(kernel=machine.kernel)

    assert result.returncode == 0, result.stdout
    assert "uv run cmake --preset pciem" in result.stdout


def test_a_second_run_fetches_nothing_when_the_checkout_is_at_the_pin(
    machine,
):
    _, before = machine.run(kernel=machine.kernel)
    result, after = machine.run(kernel=machine.kernel)

    assert result.returncode == 0, result.stdout
    assert len(calls(after, "git", "fetch")) == len(
        calls(before, "git", "fetch")
    )


def test_without_the_running_kernels_headers_it_stops_and_names_their_package(
    machine,
):
    result, lines = machine.run(release="0.0.0-spam")

    assert result.returncode != 0
    assert "sudo apt install linux-headers-0.0.0-spam" in result.stdout
    assert not calls(lines, "make")


def test_given_a_kernel_tree_that_is_not_one_it_stops_and_says_so(
    machine, tmp_path
):
    result, lines = machine.run(kernel=tmp_path)

    assert result.returncode != 0
    assert f"{tmp_path} is not a kernel build tree" in result.stdout
    assert not calls(lines, "make")


def test_on_a_machine_that_is_not_linux_it_stops_saying_pciem_is_linuxs(
    machine,
):
    result, lines = machine.run(system="Darwin", missing=frozenset({"make"}))

    assert result.returncode != 0
    assert "pciem is a Linux kernel module" in result.stdout
    assert not calls(lines, "git")


def test_without_make_it_stops_and_names_the_package(machine):
    result, lines = machine.run(
        kernel=machine.kernel, missing=frozenset({"make"})
    )

    assert result.returncode != 0
    assert "sudo apt install make" in result.stdout
    assert not calls(lines, "git")


def calls(lines, program, *words):
    """The logged commands of `program` that contain every one of `words`."""
    return [
        line
        for line in lines
        if Path(line.split()[0]).name == program
        and all(word in line.split() for word in words)
    ]
