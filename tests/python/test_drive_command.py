"""🐧 `socpuppet drive`: the puppet's drive on this machine's own bus.

The drive is the SSD with its Zephyr firmware, or 🎭 the behavioral
drive, and its host is this machine's own Linux, through pciem. The
command runs until Ctrl-C, and ends once Linux has let go of the drive.
"""

import os
import select
import signal
import subprocess
import time

import pytest

from pciem_area import needs_pciem
from processes import run_socpuppet, start_socpuppet
from socpuppet import _core
from socpuppet.boards.real_host import PCI_DEVICES, puppet_function, unbind
from socpuppet.linux import SSD_ELF
from ssd_zephyr_firmware import IMAGE as SSD_IMAGE
from this_machine import PATIENCE, block_device, rooted


class TestWhenTheSsdsFirmwareIsNotBuilt:
    def test_it_fails_with_one_line_naming_it_and_how_to_build_it(
        self, tmp_path
    ):
        ran = run_socpuppet(
            "drive", check=False, SOCPUPPET_FIRMWARE_DIR=str(tmp_path)
        )

        assert ran.returncode != 0
        said = ran.stderr.strip()
        assert "\n" not in said
        assert str(tmp_path / SSD_ELF) in said
        assert "uv run firmware/build.py zephyr" in said


@pytest.mark.skipif(_core.has_pciem, reason="this build has pciem_host")
class TestWhenTheBuildHasNoPciem:
    def test_it_fails_in_one_line_that_says_how_to_build_one(self):
        ran = run_socpuppet("drive", "--firmware", "behavioral", check=False)

        assert ran.returncode != 0
        said = ran.stderr.strip()
        assert "\n" not in said
        assert "tools/build_pciem.py" in said


@pytest.fixture
def running():
    """Starts `socpuppet` with the arguments given, as `Running`; kills
    what is still running after, so that a test that fails leaves no drive
    on the bus for the next to trip over."""
    started = []

    def start(*arguments, **extra_environment):
        started.append(Running(*arguments, **extra_environment))
        return started[-1]

    yield start
    for each in started:
        each.process.kill()
        each.process.wait()


@needs_pciem
class TestWhenTheSsdIsPutOnThisMachinesBus:
    def test_it_says_where_lsblk_lists_64_mib_and_ctrl_c_ends_it_once_let_go(
        self, running, firmware
    ):
        directory = firmware(SSD_IMAGE).parent
        drive = running("drive", SOCPUPPET_FIRMWARE_DIR=str(directory))
        drive.wait_until_it_says("Ctrl-C ends it")
        function = puppet_function()
        size = size_once_linux_lists(function)
        unbind_by_hand(function)

        drive.interrupt()

        said = drive.ended()
        assert size == 64 * 1024 * 1024
        assert str(PCI_DEVICES / function) in said
        assert "Linux has let go" in said


@needs_pciem
class TestWhenTheBehavioralDriveIsInterruptedWhileLinuxHoldsIt:
    def test_lsblk_lists_the_blocks_asked_for_and_it_says_how_to_let_go(
        self, running
    ):
        drive = running("drive", "--firmware", "behavioral", "--blocks", "2048")
        drive.wait_until_it_says("Ctrl-C ends it")
        function = puppet_function()
        size = size_once_linux_lists(function)

        drive.interrupt()

        drive.wait_until_it_says(f"sudo tee {unbind(function)}")
        assert size == 2048 * 512

    def test_it_ends_once_linux_has_let_go(self, running):
        drive = running("drive", "--firmware", "behavioral")
        drive.wait_until_it_says("Ctrl-C ends it")
        size_once_linux_lists(puppet_function())
        drive.interrupt()
        drive.wait_until_it_says("Linux still holds the drive")

        unbind_by_hand(puppet_function())

        said = drive.ended()
        assert "Linux has let go" in said
        assert "Pulled out" not in said

    def test_a_second_ctrl_c_pulls_the_drive_out(self, running):
        drive = running("drive", "--firmware", "behavioral")
        drive.wait_until_it_says("Ctrl-C ends it")
        size_once_linux_lists(puppet_function())
        drive.interrupt()
        drive.wait_until_it_says("Linux still holds the drive")

        drive.interrupt()

        said = drive.ended()
        assert "Pulled out" in said
        assert puppet_function() is None


class Running:
    """`socpuppet` running with `arguments`, and what it has said on its
    standard error."""

    def __init__(self, *arguments, **extra_environment):
        self.process = start_socpuppet(*arguments, **extra_environment)
        self.said = b""

    def wait_until_it_says(self, text):
        deadline = time.monotonic() + PATIENCE
        while text.encode() not in self.said:
            if self.process.poll() is not None or time.monotonic() > deadline:
                self.process.kill()
                pytest.fail(f"It never said {text!r}. It said:\n{self._all()}")
            self._read(within=0.1)

    def interrupt(self):
        """Ctrl-C, as a person ends it."""
        self.process.send_signal(signal.SIGINT)

    def ended(self):
        """What it said, once it has ended well, within PATIENCE."""
        try:
            status = self.process.wait(timeout=PATIENCE)
        except subprocess.TimeoutExpired:
            self.process.kill()
            pytest.fail(f"It did not end. It said:\n{self._all()}")
        said = self._all()
        assert status == 0, said
        return said

    def _read(self, within):
        stream = self.process.stderr.fileno()
        ready, _, _ = select.select([stream], [], [], within)
        if ready:
            self.said += os.read(stream, 4096)

    def _all(self):
        self.process.wait()
        while chunk := os.read(self.process.stderr.fileno(), 4096):
            self.said += chunk
        return self.said.decode(errors="replace")


def size_once_linux_lists(function):
    """How many bytes `lsblk` says the drive's namespace holds, once Linux
    has one, within PATIENCE."""
    deadline = time.monotonic() + PATIENCE
    while block_device(function) is None:
        assert time.monotonic() < deadline, "Linux never listed the drive."
        time.sleep(0.1)
    namespace = f"/dev/{block_device(function)}"
    listed = subprocess.run(
        ["lsblk", "--bytes", "--noheadings", "--output", "SIZE", namespace],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(listed)


def unbind_by_hand(function):
    """Unbind Linux's driver from the drive, as root does it by hand. The
    command pumps the drive meanwhile."""
    subprocess.run(
        rooted("tee", str(unbind(function))),
        input=function.encode(),
        capture_output=True,
        check=True,
    )
