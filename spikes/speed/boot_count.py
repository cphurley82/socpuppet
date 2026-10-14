"""How many instructions a Linux kernel takes to reach a shell (M26 step 7).

Boots Debian's prebuilt riscv64 kernel and the initrd of its installer on
QEMU's `virt` machine with `rdinit=/bin/sh`, so that the first process is
the initrd's shell, and reads off how many instructions that took.

Under `-icount shift=0` QEMU's clock advances one nanosecond for every
instruction executed, and `sleep=off` skips the time a CPU spends asleep,
so the kernel's own clock, which `dmesg` prints, is a count of
instructions. The last line `dmesg` prints at the shell is the count to
the prompt. No QEMU plugin is needed, which is as well, since Ubuntu's
QEMU ships none.

Standard library only, run with `python3 -I`, with the downloads in a
directory of their own:

    python3 -I spikes/speed/boot_count.py --downloads ~/boot-downloads
        --env native-linux-x86_64 --runs 3 >> spikes/speed/results/boot.jsonl

(one command, on one line).

⚠️ This is a distribution kernel with a 41 MB initrd, booted with OpenSBI
on QEMU's devicetree and one hart, so its count is an upper bound for
M20's boot of a small kernel with a busybox in memory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

NETBOOT = (
    "https://deb.debian.org/debian/dists/trixie/main/installer-riscv64/"
    "current/images/netboot/debian-installer/riscv64/"
)
FILES = ("linux", "initrd.gz")
# The shell's prompt in the installer's initrd, and the last timestamp of
# the kernel's log: "[   12.345678] ...".
PROMPT = re.compile(rb"(^|\n)[~/#\w-]*\s?[#$] $")
TIMESTAMP = re.compile(rb"\[\s*(\d+)\.(\d{6})\]")


def download(directory: Path) -> dict[str, str]:
    """Fetches the kernel and the initrd once, and returns their SHA-256."""
    directory.mkdir(parents=True, exist_ok=True)
    sums = {}
    for name in FILES:
        path = directory / name
        if not path.exists():
            with urllib.request.urlopen(NETBOOT + name) as response:
                path.write_bytes(response.read())
        sums[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return sums


def read_until(fd: int, pattern: re.Pattern[bytes], seconds: float) -> bytes:
    """Reads from the console until `pattern` matches what was read."""
    seen = b""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 1.0)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
        if pattern.search(seen):
            return seen
    raise TimeoutError(
        f"no {pattern.pattern!r} in {seconds} s: {seen[-400:]!r}"
    )


def boot(qemu: str, directory: Path) -> dict[str, float]:
    """One boot to the shell: the instruction count and the wall time."""
    command = [
        qemu,
        "-M",
        "virt",
        "-cpu",
        "rv64",
        "-smp",
        "1",
        "-m",
        "1G",
        "-nographic",
        "-no-reboot",
        "-kernel",
        str(directory / "linux"),
        "-initrd",
        str(directory / "initrd.gz"),
        "-append",
        "console=ttyS0 rdinit=/bin/sh",
        "-icount",
        "shift=0,sleep=off",
        "-rtc",
        "clock=vm",
    ]
    controller, console = pty.openpty()
    start = time.monotonic()
    process = subprocess.Popen(
        command, stdin=console, stdout=console, stderr=console
    )
    os.close(console)
    try:
        read_until(controller, PROMPT, 1800)
        wall = time.monotonic() - start
        os.write(controller, b"dmesg | tail -1\n")
        tail = read_until(controller, PROMPT, 60)
    finally:
        process.kill()
        process.wait()
        os.close(controller)
    stamps = TIMESTAMP.findall(tail)
    if not stamps:
        raise RuntimeError(f"no timestamp in {tail!r}")
    seconds, micros = stamps[-1]
    instructions = (int(seconds) * 1_000_000 + int(micros)) * 1000
    return {"instructions": instructions, "wall_s": round(wall, 2)}


def main() -> int:
    """Boots `--runs` times and prints one line of JSON for each."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--qemu", default="qemu-system-riscv64")
    arguments = parser.parse_args()
    qemu = shutil.which(arguments.qemu)
    if qemu is None:
        print(
            f"boot_count.py: no {arguments.qemu}. On Ubuntu it is in "
            "the package qemu-system-riscv.",
            file=sys.stderr,
        )
        return 1
    sums = download(arguments.downloads)
    version = subprocess.run(
        [qemu, "--version"], capture_output=True, text=True, check=True
    ).stdout.splitlines()[0]
    for run in range(1, arguments.runs + 1):
        result = boot(qemu, arguments.downloads)
        line = {
            "status": "boot",
            "env": arguments.env,
            "run": run,
            "qemu": version,
            "kernel": NETBOOT + "linux",
            "sha256": sums,
            **result,
        }
        print(json.dumps(line), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
