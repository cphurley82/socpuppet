"""🐧 This machine as a drive's host: finding the drive, and root's hands.

The drive's program needs no root. What the host does to the drive does:
reading its registers through /sys, and formatting and mounting it. Each
of those is run with `sudo -n`, which the doctor's `pciem` area checks
asks no password (pciem_area.py).
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from socpuppet.boards.drive import DEVICE_ID, VENDOR_ID
from socpuppet.pump import pump

PCI_DEVICES = Path("/sys/bus/pci/devices")
#: The IDs the puppet's drive says: its vendor, and which device it is.
PUPPET = (VENDOR_ID, DEVICE_ID)
#: How long, on the wall, a test waits for this machine's Linux, so that
#: what never comes fails the test and does not hang it. Linux waits for a
#: drive's commands for 30 s, and gets each answer in well under one.
PATIENCE = 30.0


def puppet_function() -> str | None:
    """The PCI address of the puppet's drive on pciem's bus, if it is on it.

    Found by where it is, never by a name a driver gave it: on pciem's own
    bus, with the puppet's IDs. There is one at most, or a drive from
    before is still there, and the test would not know which is its own.
    """
    found = [
        device.name
        for device in sorted(PCI_DEVICES.iterdir())
        if "pciem" in str(device.resolve()) and ids_of(device) == PUPPET
    ]
    if len(found) > 1:
        raise AssertionError(
            f"two puppet drives on pciem's bus, {found}: one from before is"
            " still there"
        )
    return found[0] if found else None


def ids_of(device: Path) -> tuple[int, int]:
    """Who made `device`, and which device it is, as it says."""
    return (
        int((device / "vendor").read_text(), 16),
        int((device / "device").read_text(), 16),
    )


def what_the_host_reads(function: str, offset: int, size: int) -> bytes:
    """The `size` bytes at `offset` of the drive's registers, as the host
    reads them: pciem's copy of BAR0, which root maps through /sys.
    """
    resource = PCI_DEVICES / function / "resource0"
    script = (
        "import mmap, os, sys\n"
        f"fd = os.open({str(resource)!r}, os.O_RDONLY)\n"
        f"bar = mmap.mmap(fd, {offset + size}, mmap.MAP_SHARED, mmap.PROT_READ)\n"
        f"sys.stdout.buffer.write(bar[{offset}:{offset + size}])\n"
    )
    return as_root(sys.executable, "-I", "-c", script)


def scribble_on(function: str, data: bytes) -> None:
    """Put `data` at the start of pciem's copy of the drive's registers,
    behind the drive's back.

    The bytes land in the memory the host reads, but the drive never hears
    of them: pciem sees only the writes the kernel makes through its own
    mapping of the registers, and root's mapping through /sys is not that.
    """
    resource = PCI_DEVICES / function / "resource0"
    script = (
        "import mmap, os, sys\n"
        f"fd = os.open({str(resource)!r}, os.O_RDWR)\n"
        f"bar = mmap.mmap(fd, {len(data)}, mmap.MAP_SHARED)\n"
        f"bar[:] = {data!r}\n"
    )
    as_root(sys.executable, "-I", "-c", script)


def as_root(*argv: str) -> bytes:
    """Run `argv` as root, asking no password; returns what it printed."""
    return subprocess.run(
        ["sudo", "-n", *argv], capture_output=True, check=True
    ).stdout


def block_device(function: str) -> str | None:
    """The name of the drive's namespace, `nvmeXn1`, once Linux has one.

    Found under the function, by where it is: never by the name alone,
    since this machine may have NVMe drives of its own.
    """
    found = list((PCI_DEVICES / function / "nvme").glob("nvme*/nvme*n1"))
    if not found:
        return None
    (namespace,) = found
    return namespace.name


def block_size(device: str) -> int:
    """How many bytes a block of `device` is, as Linux says."""
    name = Path(device).name
    return int(Path("/sys/block", name, "queue/logical_block_size").read_text())


def write_block(board, device: str, block: bytes) -> None:
    """Write `block` as the first block of `device`, while `board` is
    pumped. Past Linux's page cache, so that it goes to the drive."""
    as_root_while_pumping(
        board,
        "dd",
        f"of={device}",
        "oflag=direct",
        f"bs={len(block)}",
        "count=1",
        given=block,
    )


def read_block(board, device: str) -> bytes:
    """The first block of `device`, read while `board` is pumped. Past
    Linux's page cache, so that it comes from the drive."""
    return as_root_while_pumping(
        board,
        "dd",
        f"if={device}",
        "iflag=direct",
        f"bs={block_size(device)}",
        "count=1",
    )


def pumped_until(board, condition, patience: float = PATIENCE) -> bool:
    """Pump `board`'s platform with its host until `condition`, or until
    `patience` seconds on the wall have passed. Returns `condition()`.
    """
    started = time.monotonic()
    pump(
        board.platform,
        far_ends=[board.host],
        until=lambda: condition() or time.monotonic() - started > patience,
    )
    return condition()


def let_go(board) -> None:
    """Unbind the driver that holds the drive, if one does, while `board`
    is pumped.

    The driver finishes with the drive as it lets go, so the drive must
    still answer then. A platform that ends with a driver holding its
    drive leaves the driver waiting for answers that never come, and pciem
    waiting for the driver: half a minute, for each command it was owed.
    """
    function = puppet_function()
    driver = PCI_DEVICES / function / "driver"
    if driver.exists():
        as_root_while_pumping(
            board, "tee", str(driver / "unbind"), given=function.encode()
        )


def as_root_while_pumping(board, *argv: str, given: bytes = b"") -> bytes:
    """Run `argv` as root while `board` is pumped, which a command that
    uses the drive needs: the drive answers only while its platform runs.

    `given` is the command's standard input. Returns what it printed, and
    raises if it fails or takes longer than PATIENCE.
    """
    with tempfile.TemporaryFile() as output:
        command = subprocess.Popen(
            ["sudo", "-n", *argv],
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.PIPE,
        )
        command.stdin.write(given)
        command.stdin.close()
        if not pumped_until(board, lambda: command.poll() is not None):
            command.kill()
            raise TimeoutError(f"{' '.join(argv)} took over {PATIENCE} s")
        if command.returncode:
            raise subprocess.CalledProcessError(
                command.returncode, argv, stderr=command.stderr.read()
            )
        output.seek(0)
        return output.read()
