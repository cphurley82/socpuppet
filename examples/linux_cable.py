"""🔌 Linux on the host, a cable to this machine, and ssh down it.

    ssh ─▶ 127.0.0.1:port ─▶ libslirp ─▶ cable ─▶ 🎭 virtio card ─▶ Linux :22
                                  └─▶ cable.pcap, for Wireshark

Linux boots to its prompt as fast as the simulation goes. Then a cable is
plugged into its network card, 🎭 the virtio one: `sp.EthernetCable`,
with libslirp behind it, QEMU's user-mode network, which needs no root.
Linux takes an address by DHCP, and a port of this machine's is forwarded
to its port 22, where dropbear, Alpine's SSH server, answers. This
machine's own `ssh` then runs `uname -a` there, while Python keeps the
simulation running: a far end outside the simulation is pumped
(`socpuppet.pump.pump`), so that the simulated clock keeps to the wall's
while Linux waits, and slirp's sockets are served as they become ready.

Every frame both ways is written to `cable.pcap` in the current
directory, which Wireshark and `tcpdump -nr cable.pcap` open: DHCP, ARP,
and the TCP of the ssh session.

Build the firmware first:   uv run firmware/build.py
Install libslirp:           uv run python tools/doctor.py cable
Run it:                     python examples/linux_cable.py

The images are looked for in build/firmware, or in SOCPUPPET_FIRMWARE_DIR
if that is set. With an image missing the example says so and counts as
not run, unless SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where a
missing image is a failure; the same for libslirp and ssh, under
SOCPUPPET_REQUIRE_CABLE, as the cable's tests have it.
"""

import functools
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time

import socpuppet as sp
from socpuppet import linux
from socpuppet.boards.host import switched_off
from socpuppet.pump import pump
from socpuppet.run import firmware_directory
from socpuppet.slirp import Slirp

IMAGES = firmware_directory()
CAPTURE = pathlib.Path("cable.pcap")
#: How long the kernel may take to prompt, in simulated time.
PROMPTS_WITHIN = sp.ms(400_000)
#: How long, on the wall, ssh may take, tries and all: Linux asks for its
#: address again 20 s of the CPU's time after its last try, the keys of a
#: connection are made on the simulated CPU, and dropbear makes its host
#: key at the first connection.
SSH_PATIENCE = 300.0
#: How long, on the wall, Linux is given between two tries of ssh.
BETWEEN_TRIES = 1.0
#: How long, on the wall, `poweroff` may take: busybox stops every process
#: and unmounts the disk first, on a clock that now keeps to the wall's.
SWITCHES_OFF_WITHIN = 60.0
#: How this machine's ssh is told to reach Linux: no configuration of this
#: machine's own, no host key to check or keep, since Linux's is new at
#: each boot, and no question to wait on an answer to.
SSH_OPTIONS = (
    *("-F", "/dev/null"),
    *("-o", "StrictHostKeyChecking=no"),
    *("-o", "UserKnownHostsFile=/dev/null"),
    *("-o", "LogLevel=ERROR"),
    *("-o", "BatchMode=yes"),
)
#: The classic pcap format: a file header, then each frame after a record
#: header of its own, whose third field is how many bytes of the frame
#: were captured. `socpuppet.ethernet_cable` writes it.
PCAP_FILE_HEADER = 24
PCAP_RECORD_HEADER = 16
PCAP_CAPTURED_LENGTH = slice(8, 12)


def what_the_cable_lacks() -> str | None:
    """What this machine lacks for the cable: libslirp, or ssh."""
    try:
        Slirp(send=lambda frame: None).close()
    except sp.SlirpUnavailable as refused:
        return str(refused)
    if shutil.which("ssh") is None:
        return "There is no ssh on this machine. `tools/doctor.py cable` says."
    return None


def a_free_port() -> int:
    """A TCP port of this machine's that nothing listens on, just now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def has_ended(process):
    """Whether `process`, started on this machine, has ended."""
    return process.poll() is not None


def pump_for(board, cable, seconds, *, until=lambda: False):
    """Run the platform with the cable for `seconds` on the wall, or until."""
    deadline = time.monotonic() + seconds
    pump(
        board.platform,
        far_ends=[cable],
        until=lambda: until() or time.monotonic() > deadline,
    )


def ssh(board, cable, port, command):
    """What `command` prints, run on Linux by this machine's ssh.

    ⚠️ Linux answers only while its platform runs, so the platform is
    pumped with the cable while ssh runs. A try that fails is made again
    after `BETWEEN_TRIES`, since Linux's address or its SSH server may not
    be there yet, until `SSH_PATIENCE` has passed.
    """
    started = time.monotonic()
    while True:
        process = subprocess.Popen(
            ("ssh", *SSH_OPTIONS, "-p", str(port), "root@localhost", command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        left = SSH_PATIENCE - (time.monotonic() - started)
        pump_for(
            board, cable, left, until=functools.partial(has_ended, process)
        )
        if not has_ended(process):
            process.kill()
            sys.exit(f"❌ ssh took over {SSH_PATIENCE:.0f} s.")
        output, errors = process.communicate()
        if process.returncode == 0:
            return output.decode()
        if time.monotonic() - started > SSH_PATIENCE:
            sys.exit(f"❌ ssh kept failing: {errors.decode().strip()}")
        pump_for(board, cable, BETWEEN_TRIES)


def frames_in(capture):
    """How many frames a pcap file holds."""
    data = capture.read_bytes()
    at, count = PCAP_FILE_HEADER, 0
    while at + PCAP_RECORD_HEADER <= len(data):
        header = data[at : at + PCAP_RECORD_HEADER]
        captured = int.from_bytes(header[PCAP_CAPTURED_LENGTH], "little")
        at += PCAP_RECORD_HEADER + captured
        count += 1
    return count


if __name__ == "__main__":
    # The firmware is looked for first, as every example that boots some
    # does, so that where it is missing this one says so the same way.
    try:
        board = linux.host_with_linux(IMAGES)
    except FileNotFoundError as missing:
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            sys.exit(str(missing))
        print(missing)
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)
    if lacks := what_the_cable_lacks():
        if os.environ.get("SOCPUPPET_REQUIRE_CABLE"):
            sys.exit(lacks)
        print(lacks)
        sys.exit(77)
    console = board.virtio.console
    cpu = board.cpu.component.implementation
    print(
        f"🧦 Booting 🐧 Linux on the host's {cpu}, as fast as the simulation "
        "goes.",
        flush=True,
    )
    if not board.platform.run_until(
        lambda: linux.PROMPT.search(console.output) is not None,
        timeout=PROMPTS_WITHIN,
    ):
        sys.exit(f"❌ Linux never prompted. Its console:\n{console.output}")
    print(
        f"✅ The shell prompted at {board.platform.time / sp.s(1):.0f} s of "
        "simulated time."
    )

    port = a_free_port()
    with sp.EthernetCable(
        board.virtio.net, forward={port: 22}, capture=CAPTURE
    ) as cable:
        print(
            f"🔌 The cable is in: this machine's port {port} reaches Linux's "
            f"22, and the frames go to {CAPTURE}. Running ssh...",
            flush=True,
        )
        started = time.monotonic()
        answer = ssh(board, cable, port, "uname -a")
        print(f"\n🧵 ssh -p {port} root@localhost uname -a")
        print(answer, end="")
        print(f"✅ Answered in {time.monotonic() - started:.0f} s on the wall.")

        console.write("poweroff\n")
        pump_for(
            board, cable, SWITCHES_OFF_WITHIN, until=lambda: switched_off(board)
        )
        if not switched_off(board):
            sys.exit("\n❌ Linux did not switch the host off.")
    print(
        f"\n🐧 Linux switched the host off. {CAPTURE} holds the capture, "
        f"{frames_in(CAPTURE)} frames: `tcpdump -nr {CAPTURE}` or Wireshark "
        "reads it."
    )
