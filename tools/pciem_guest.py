#!/usr/bin/env python3
"""Run a command as root in a QEMU guest of this machine's, with pciem.

Usage:
  uv run tools/pciem_guest.py -- .venv/bin/python -m pytest tests/python

🐧 The tests of a real host need pciem loaded, which needs root and memory
set aside at boot: what a CI runner cannot give the machine it runs on.
So this boots this machine's own kernel in QEMU, as pciem's own CI does,
with this machine's root as the guest's, shared over 9p, so that the
guest has the checkout, its build and its venv as they are. The guest
loads pciem, set aside in memory the guest's kernel is told it does not
have, and Linux's nvme driver, then runs the command as root, in the
directory this was run from. It says the command's exit status on its
console, which is how it reaches this side, and this ends with it.

The kernel is /boot/vmlinuz-RELEASE, which on Ubuntu only root can read
(`sudo chmod a+r` it), and pciem's module is the one tools/build_pciem.py
built for it. QEMU runs the guest on KVM, which /dev/kvm must let this
user open: without it, the guest is too slow for Linux's timeouts.
"""

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from needs import Failed, not_installed

REPOSITORY = Path(__file__).resolve().parents[1]

# What the guest needs of this machine: each program, and the Ubuntu
# package it comes in. busybox is the initramfs's shell, and must be the
# static one: the initramfs has no libraries.
PROGRAMS = (
    ("qemu-system-x86_64", "qemu-system-x86"),
    ("busybox", "busybox-static"),
    ("zstd", "zstd"),
)

# The initramfs's directories: root is where this machine's goes.
DIRECTORIES = ("bin", "dev", "lib", "lib/modules", "root")

# The modules the initramfs loads to mount the root over 9p: the virtio
# transport and the filesystem. modules.dep says what they need first.
NINE_P = ("kernel/net/9p/9pnet_virtio.ko.zst", "kernel/fs/9p/9p.ko.zst")

# The root's mount: 9p's Linux dialect, and half a megabyte at a time.
NINE_P_OPTIONS = "trans=virtio,version=9p2000.L,msize=524288"

# The guest has MEMORY and its kernel is told it has GUEST_SEES: pciem's
# region is the first 64 MiB of the rest, which nothing else uses, as
# memmap= does on a machine of its own.
MEMORY = "4G"
GUEST_SEES = "2G"
PCIEM_REGION = "0x80000000:0x4000000"

# What the command is given of this side's environment: where its programs
# are, and its home, where uv keeps its Pythons.
PASSED_ON = ("PATH", "HOME")

# How the guest says how the command went, alone on a line of its console.
RESULT = re.compile(r"^RESULT: (\d+)$")


def main() -> int:
    """Boot the guest and run the command. Returns its exit status."""
    parser = argparse.ArgumentParser(
        prog="tools/pciem_guest.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--kernel",
        type=Path,
        help="the kernel to boot (default: the running one's, "
        "/boot/vmlinuz-RELEASE)",
    )
    parser.add_argument(
        "--modules",
        type=Path,
        help="the kernel's modules (default: /lib/modules/RELEASE)",
    )
    parser.add_argument(
        "--pciem",
        type=Path,
        default=REPOSITORY / "build" / "pciem" / "kernel" / "pciem.ko",
        help="pciem's module, built for the kernel "
        "(build/pciem/kernel/pciem.ko)",
    )
    parser.add_argument("command", nargs="+", help="what to run, as root")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    release = os.uname().release
    try:
        busybox = programs()
        kernel = args.kernel or Path("/boot") / f"vmlinuz-{release}"
        if not os.access(kernel, os.R_OK):
            raise Failed(
                f"{kernel} cannot be read, and QEMU boots it.\n"
                f"Let it be: sudo chmod a+r {kernel}"
            )
        modules = args.modules or Path("/lib/modules") / release
        loads = load_order(modules, NINE_P)
        script = init(
            loads=loads,
            pciem=args.pciem,
            command=args.command,
            directory=Path.cwd(),
            environment={name: os.environ.get(name, "") for name in PASSED_ON},
            busybox=busybox,
        )
        with tempfile.TemporaryDirectory() as scratch:
            initramfs = Path(scratch) / "initramfs.cpio"
            initramfs.write_bytes(
                packed(guest_files(modules, loads, busybox, script))
            )
            return boot(kernel, initramfs)
    except Failed as failure:
        print(f"pciem_guest.py: {failure}", file=sys.stderr)
        return 1


def programs() -> Path:
    """Where busybox is.

    Stops, naming the packages to install, if a program is missing.
    """
    if missing := not_installed(PROGRAMS):
        raise Failed.without("The guest cannot be run", missing)
    return Path(shutil.which("busybox") or "")


def load_order(modules: Path, wanted: tuple[str, ...]) -> list[str]:
    """`wanted`, each after the modules it needs, as modules.dep says.

    modules.dep names every module a module needs, nearest first, so the
    last of them loads first.
    """
    needs = {}
    for line in (modules / "modules.dep").read_text().splitlines():
        module, _, needed = line.partition(":")
        needs[module] = needed.split()
    order: list[str] = []
    for module in wanted:
        for each in [*reversed(needs[module]), module]:
            if each not in order:
                order.append(each)
    return order


def in_initramfs(module: str) -> str:
    """Where `module`, from modules.dep, goes in the initramfs."""
    return f"lib/modules/{Path(module).name.removesuffix('.zst')}"


def guest_files(
    modules: Path, loads: list[str], busybox: Path, init: str
) -> dict[str, bytes | None]:
    """The initramfs's files by name, with None for a directory.

    busybox, the modules of `loads` from `modules`, decompressed, and
    `init`.
    """
    files: dict[str, bytes | None] = dict.fromkeys(DIRECTORIES)
    files["bin/busybox"] = busybox.read_bytes()
    for module in loads:
        files[in_initramfs(module)] = subprocess.run(
            ["zstd", "-dcq", str(modules / module)],
            capture_output=True,
            check=True,
        ).stdout
    files["init"] = init.encode()
    return files


def init(
    *,
    loads: list[str],
    pciem: Path,
    command: list[str],
    directory: Path,
    environment: dict[str, str],
    busybox: Path,
) -> str:
    """The initramfs's /init, which runs `command` on this machine's root.

    It loads the modules of `loads`, mounts the root over 9p and goes over
    to it, where it loads pciem and Linux's nvme driver, then runs
    `command` as root in `directory`, given `environment`. Then the guest
    is switched off by `busybox`, this machine's, which its root has.
    """
    insmods = "\n".join(
        f"/bin/busybox insmod /{in_initramfs(module)}" for module in loads
    )
    given = " ".join(
        f"{name}={shlex.quote(value)}" for name, value in environment.items()
    )
    return f"""#!/bin/busybox sh
{insmods}
/bin/busybox mount -t 9p -o {NINE_P_OPTIONS} root /root
guest=$(/bin/busybox cat <<'GUEST'
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs dev /dev
mount -t tmpfs tmp /tmp
mount -t tmpfs run /run
insmod {shlex.quote(str(pciem))} pciem_phys_region={PCIEM_REGION}
modprobe nvme
cd {shlex.quote(str(directory))}
env {given} {shlex.join(command)}
echo "RESULT: $?"
sync
exec {shlex.quote(str(busybox))} poweroff -f
GUEST
)
exec /bin/busybox switch_root /root /bin/sh -c "$guest"
"""


def boot(kernel: Path, initramfs: Path) -> int:
    """Boot the guest; returns the status it says the command ended with.

    Its console is shown here as it goes.
    """
    qemu = subprocess.Popen(
        [
            *("qemu-system-x86_64", "-machine", "accel=kvm", "-cpu", "max"),
            *("-smp", str(os.cpu_count() or 1), "-m", MEMORY),
            *("-kernel", str(kernel), "-initrd", str(initramfs)),
            "-append",
            f"console=ttyS0 quiet mem={GUEST_SEES} panic=1",
            *("-fsdev", "local,id=root,path=/,security_model=none"),
            *("-device", "virtio-9p-pci,fsdev=root,mount_tag=root"),
            *("-nographic", "-no-reboot"),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    assert qemu.stdout is not None
    status = None
    for line in qemu.stdout:
        line = line.rstrip("\r\n")
        print(line)
        if said := RESULT.match(line):
            status = int(said[1])
    qemu.wait()
    if status is None:
        raise Failed(
            "the guest never said how the command went (QEMU ended with "
            f"{qemu.returncode}); what it said above says why."
        )
    return status


def packed(files: dict[str, bytes | None]) -> bytes:
    """`files` as an initramfs: a cpio archive in the "newc" format.

    Each file may be run, which the modules do not mind. With the console
    the kernel opens for init, as a device of its own.
    """
    archive = bytearray()

    def add(name: str, mode: int, data: bytes = b"", device=(0, 0)) -> None:
        fields = [
            len(archive),  # inode: any number, each its own
            mode,
            0,  # uid
            0,  # gid
            1,  # links
            0,  # mtime
            len(data),
            0,  # the device it is on
            0,
            *device,  # what it is, for a device
            len(name) + 1,
            0,  # check
        ]
        archive.extend(b"070701" + "".join(f"{f:08x}" for f in fields).encode())
        archive.extend(name.encode() + b"\0")
        archive.extend(bytes(-len(archive) % 4))
        archive.extend(data)
        archive.extend(bytes(-len(archive) % 4))

    for name, data in files.items():
        if data is None:
            add(name, 0o040755)
        else:
            add(name, 0o100755, data)
    add("dev/console", 0o020600, device=(5, 1))
    add("TRAILER!!!", 0)
    return bytes(archive)


if __name__ == "__main__":
    sys.exit(main())
