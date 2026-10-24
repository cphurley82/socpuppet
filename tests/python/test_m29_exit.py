"""M29's exit test: ssh from this machine to Linux, over a cable.

🔌 Linux's network card, 🎭 the virtio network device, is plugged into this
machine's network by `sp.EthernetCable`, through libslirp, with no root.
Linux gets its address by DHCP, dropbear answers ssh on port 22, and the
cable forwards a port of this machine's to it. Then this machine's own ssh
runs `uname -a` there, and its scp sends a file, which the shell on the
console reads back.

    ssh, scp ─▶ 127.0.0.1:port ─▶ slirp ─▶ cable ─▶ eth0 ─▶ dropbear :22

It runs on whichever hart SOCPUPPET_CPU names: CI runs it on both.
"""

import hashlib
import random
import subprocess
import time
from pathlib import Path
from typing import NamedTuple

import pytest

import socpuppet as sp
from cable_area import needs_cable
from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    a_host_with_linux,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)
from sockets import a_free_port
from socpuppet.boards.host import Host
from socpuppet.pump import pump

#: A boot of Linux takes seconds on QBox's hart and minutes on the
#: interpreter, so the tests are handed out first.
pytestmark = [needs_cable, needs_dtc, pytest.mark.long, pytest.mark.platform]

#: How long, on the wall, an ssh or an scp may take, tries and all: udhcpc
#: asks again 20 s of the CPU's time after its last try, the keys of a
#: connection are made on the simulated CPU, and dropbear makes its own
#: host key at the first connection.
SSH_PATIENCE = 300.0
#: The file scp sends: as many bytes as take TCP through many windows.
FILE_SIZE = 256 * 1024
#: How this machine's ssh is told to reach Linux. No configuration of this
#: machine's own (-F /dev/null), and no host key to check or keep: Linux's
#: is made afresh on each boot.
SSH_OPTIONS = (
    *("-F", "/dev/null"),
    *("-o", "StrictHostKeyChecking=no"),
    *("-o", "UserKnownHostsFile=/dev/null"),
    *("-o", "LogLevel=ERROR"),
    *("-o", "BatchMode=yes"),
)


class Plugged(NamedTuple):
    """Linux at its prompt, with a cable plugged in, and the port of this
    machine's that is forwarded to its port 22."""

    board: Host
    cable: sp.EthernetCable
    port: int


@pytest.fixture
def linux_on_the_cable(firmware):
    """A host that has booted Linux to its prompt, with a cable plugged in.

    💡 Linux boots as fast as the simulation goes, and the cable is
    plugged in at the prompt: a boot that is pumped keeps to the wall's
    clock while the CPU sleeps, which on QBox's hart is minutes of a boot
    that otherwise takes seconds. udhcpc, asking in the background, gets
    its address at its next try.
    """
    board = a_host_with_linux(firmware)
    assert run_to_the_prompt(board), (
        f"Linux never prompted. The console:\n"
        f"{plain(board.virtio.console.output)}"
    )
    port = a_free_port()
    with sp.EthernetCable(board.virtio.net, forward={port: 22}) as cable:
        yield Plugged(board, cable, port)


class TestWhenThisMachinesSshRunsUnameOnLinux:
    def test_linux_answers_as_it_does_at_its_console(self, linux_on_the_cable):
        by_ssh = ssh(linux_on_the_cable, "uname -a")

        at_the_console = type_and_wait_for_the_prompt(
            linux_on_the_cable.board, "uname -a"
        )
        assert by_ssh.strip() == at_the_console.strip()


class TestWhenThisMachinesScpSendsAFileToLinux:
    def test_the_shell_on_the_console_reads_it_back(
        self, linux_on_the_cable, tmp_path
    ):
        sent = tmp_path / "spam"
        sent.write_bytes(random.Random(1).randbytes(FILE_SIZE))

        scp(linux_on_the_cable, sent, "/root/spam")

        answer = type_and_wait_for_the_prompt(
            linux_on_the_cable.board, "sha256sum /root/spam"
        )
        assert (
            answer.split()[0] == hashlib.sha256(sent.read_bytes()).hexdigest()
        )


def ssh(linux: Plugged, command: str) -> str:
    """What `command` prints, run as root on `linux` by this machine's ssh."""
    printed = while_pumping(
        linux,
        "ssh",
        *SSH_OPTIONS,
        *("-p", str(linux.port)),
        "root@localhost",
        command,
    )
    return printed.decode()


def scp(linux: Plugged, sent: Path, to: str) -> None:
    """Send `sent`, a file of this machine's, to `to` on `linux` by scp."""
    while_pumping(
        linux,
        "scp",
        *SSH_OPTIONS,
        *("-P", str(linux.port)),
        str(sent),
        f"root@localhost:{to}",
    )


def while_pumping(linux: Plugged, *argv: str) -> bytes:
    """Run `argv` on this machine while `linux` is pumped with its cable.

    ⚠️ Linux answers only while its platform runs. Its address or dropbear
    may not be there yet when the first try comes, so a try that fails is
    made again, until SSH_PATIENCE. Returns what the command printed.
    """
    started = time.monotonic()
    while True:
        command = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        left = SSH_PATIENCE - (time.monotonic() - started)
        if not pumped_until(
            linux, lambda done=command.poll: done() is not None, left
        ):
            command.kill()
            raise TimeoutError(f"{argv[0]} took over {SSH_PATIENCE} s")
        output, errors = command.communicate()
        if command.returncode == 0:
            return output
        if time.monotonic() - started > SSH_PATIENCE:
            raise subprocess.CalledProcessError(
                command.returncode, argv, output, errors
            )


def pumped_until(linux: Plugged, condition, patience: float) -> bool:
    """Pump `linux`'s platform with its cable until `condition`, or until
    `patience` seconds on the wall have passed. Returns `condition()`.
    """
    started = time.monotonic()
    pump(
        linux.board.platform,
        far_ends=[linux.cable],
        until=lambda: (
            bool(condition()) or time.monotonic() - started > patience
        ),
    )
    return bool(condition())
