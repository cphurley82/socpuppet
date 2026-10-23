"""tools/pciem_guest.py, which runs a command as root in a QEMU guest.

The guest is this machine's own kernel, with this machine's root as its
own, and pciem loaded. The script is run for real, with stand-ins for
QEMU, busybox and zstd on its path. The stand-in QEMU logs what it
was given, keeps the initramfs it was handed, and prints a console the
test chooses, so the tests can say what the guest would do without
booting one.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "pciem_guest.py"

# A QEMU that keeps the initramfs it is given, then prints the console.
QEMU = """
import os, shutil
args = sys.argv[1:]
shutil.copy(args[args.index("-initrd") + 1], os.environ["KEPT"])
print(os.environ["CONSOLE"], end="")
"""

# A zstd that decompresses by printing the file as it is.
ZSTD = """
sys.stdout.buffer.write(open(sys.argv[-1], "rb").read())
"""

# The modules 9p needs, as this machine's kernel has them, and every module
# each needs, the nearest first.
MODULES_DEP = """\
kernel/fs/9p/9p.ko.zst: kernel/net/9p/9pnet.ko.zst kernel/fs/netfs/netfs.ko.zst
kernel/net/9p/9pnet.ko.zst: kernel/fs/netfs/netfs.ko.zst
kernel/net/9p/9pnet_virtio.ko.zst: kernel/net/9p/9pnet.ko.zst kernel/fs/netfs/netfs.ko.zst
kernel/fs/netfs/netfs.ko.zst:
kernel/drivers/nvme/host/nvme.ko.zst: kernel/drivers/nvme/host/nvme-core.ko.zst
"""


@dataclass
class Machine:
    """A machine of stand-ins to run the script on: its kernel, its
    modules and pciem's, and where the stand-in QEMU keeps the initramfs.
    """

    bin: Path
    log: Path
    kernel: Path
    modules: Path
    pciem: Path
    kept: Path

    def run(
        self,
        *command: str,
        console: str = "RESULT: 0\n",
        missing: frozenset[str] = frozenset(),
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        """Run the script with `command`; returns its result and the
        commands it ran."""
        for program in missing:
            (self.bin / program).unlink()
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--kernel",
                str(self.kernel),
                "--modules",
                str(self.modules),
                "--pciem",
                str(self.pciem),
                "--",
                *command,
            ],
            env={
                **os.environ,
                "PATH": str(self.bin),
                "CONSOLE": console,
                "KEPT": str(self.kept),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return result, lines

    def initramfs(self) -> dict[str, bytes]:
        """The files of the initramfs the guest was given, by name."""
        return unpacked(self.kept.read_bytes())


@pytest.fixture
def machine(tmp_path):
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = tmp_path / "log"
    logger = f"open({str(log)!r}, 'a').write(' '.join(sys.argv) + '\\n')\n"
    programs = {
        "qemu-system-x86_64": QEMU,
        "zstd": ZSTD,
        "busybox": "",
    }
    for name, body in programs.items():
        program = bin_directory / name
        program.write_text(
            f"#!{sys.executable}\nimport os, sys\n{logger}{body}"
        )
        program.chmod(0o755)
    kernel = tmp_path / "vmlinuz"
    kernel.write_bytes(b"a kernel")
    modules = tmp_path / "modules"
    for line in MODULES_DEP.splitlines():
        module = modules / line.split(":")[0]
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_bytes(module.name.encode())
    (modules / "modules.dep").write_text(MODULES_DEP)
    pciem = tmp_path / "pciem.ko"
    pciem.write_bytes(b"pciem")
    return Machine(
        bin_directory, log, kernel, modules, pciem, tmp_path / "initramfs"
    )


class TestWhenTheCommandEndsInTheGuest:
    def test_the_script_ends_as_it_did(self, machine):
        result, _ = machine.run("false", console="spam\r\nRESULT: 3\r\n")

        assert result.returncode == 3, result.stdout

    def test_what_the_guest_said_on_its_console_is_shown(self, machine):
        result, _ = machine.run("true", console="eggs\r\nRESULT: 0\r\n")

        assert "eggs" in result.stdout


class TestWhenTheScriptRunsACommand:
    def test_the_guest_is_the_kernel_it_is_given_with_this_machines_root_over_9p(
        self, machine
    ):
        _, lines = machine.run("true")

        (qemu,) = calls(lines, "qemu-system-x86_64")
        assert f"-kernel {machine.kernel}" in qemu
        assert "virtio-9p-pci" in qemu
        assert "local,id=root,path=/," in qemu

    def test_the_guest_loads_what_9p_needs_each_after_what_it_needs(
        self, machine
    ):
        machine.run("true")

        init = machine.initramfs()["init"].decode()
        loaded = [
            init.index(f"/lib/modules/{name}.ko")
            for name in ("netfs", "9pnet", "9pnet_virtio", "9p")
        ]
        assert loaded == sorted(loaded)
        assert machine.initramfs()["lib/modules/9p.ko"] == b"9p.ko.zst"

    def test_the_guest_loads_pciem_then_runs_the_command_in_the_workspace(
        self, machine
    ):
        machine.run("pytest", "tests/spam and eggs")

        init = machine.initramfs()["init"].decode()
        pciem = init.index(f"insmod {machine.pciem} pciem_phys_region=")
        command = init.index("pytest 'tests/spam and eggs'")
        assert pciem < command
        assert f"cd {os.getcwd()}" in init


class TestWhenTheGuestEndsWithoutSayingHowTheCommandWent:
    def test_the_script_fails_saying_so(self, machine):
        result, _ = machine.run("true", console="Kernel panic\r\n")

        assert result.returncode != 0
        assert "never said how the command went" in result.stdout


@pytest.mark.parametrize(
    ("program", "package"),
    [
        ("qemu-system-x86_64", "qemu-system-x86"),
        ("busybox", "busybox-static"),
        ("zstd", "zstd"),
    ],
)
def test_without_a_program_it_stops_and_names_its_package(
    machine, program, package
):
    result, lines = machine.run("true", missing=frozenset({program}))

    assert result.returncode != 0
    assert f"sudo apt install {package}" in result.stdout
    assert not calls(lines, "qemu-system-x86_64")


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_when_the_kernel_is_not_readable_it_says_how_to_make_it_so(machine):
    machine.kernel.chmod(0)

    result, lines = machine.run("true")

    assert result.returncode != 0
    assert f"sudo chmod a+r {machine.kernel}" in result.stdout
    assert not calls(lines, "qemu-system-x86_64")


def calls(lines, program, *words):
    """The logged commands of `program` that contain every one of `words`."""
    return [
        line
        for line in lines
        if Path(line.split()[0]).name == program
        and all(word in line for word in words)
    ]


def unpacked(archive: bytes) -> dict[str, bytes]:
    """The regular files of a cpio archive in the "newc" format."""
    files = {}
    at = 0
    while True:
        header = archive[at : at + 110]
        mode = int(header[14:22], 16)
        size = int(header[54:62], 16)
        name_size = int(header[94:102], 16)
        name = archive[at + 110 : at + 110 + name_size - 1].decode()
        if name == "TRAILER!!!":
            return files
        data_at = _aligned(at + 110 + name_size)
        if mode & 0o170000 == 0o100000:
            files[name] = archive[data_at : data_at + size]
        at = _aligned(data_at + size)


def _aligned(offset: int) -> int:
    return (offset + 3) & ~3
