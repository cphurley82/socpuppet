"""M20's exit test: Linux boots on OpenSBI, to a shell Python types at.

🐧 The kernel is a stock one, built by `firmware/build.py` as Linux's own
`defconfig`, with nothing of socpuppet's in it. OpenSBI's `fw_jump` starts
it 2 MiB into RAM with the devicetree the host writes, and it reads its
hardware from there: the AIA interrupt controllers, the 16550, and 🎭 the
five virtio devices. Its console is the virtio console and its root
filesystem is the virtio disk, with Alpine's mini root on it and an
inittab of ours that puts a shell on the console (`firmware/rootfs`).

It boots the quick way, with Python as the stage before OpenSBI.

🧵 Python is the keyboard at the console, as at UEFI's shell in M28.
"""

import re
import tomllib
from pathlib import Path

import pytest

from cast import LINUX_BIN, ROOTFS_EXT4
from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    BOOTARGS,
    PROMPT,
    SWITCHES_OFF_WITHIN,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)
from opensbi_boots import a_host_with_opensbi, loaded_by_python, switched_off
from socpuppet.boards.virtio import Virtio

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. A boot
#: of Linux takes seconds on QBox's hart and minutes on the interpreter, so
#: the tests are handed out first.
pytestmark = [needs_dtc, pytest.mark.long]

#: What the kernel says first, with its version: "Linux version 6.18.57".
BANNER = re.compile(r"Linux version (\d+\.\d+\.\d+)")
#: The kernel firmware/build.py builds, as versions.toml pins it.
VERSIONS = Path(__file__).resolve().parents[2] / "firmware" / "versions.toml"
#: A virtio disk's sector.
SECTOR = 512


@pytest.fixture
def linux_at_its_prompt(firmware):
    """A host that has booted OpenSBI and Linux the quick way, to the prompt.

    Or for `LONG_ENOUGH`, if the prompt never comes.
    """
    rootfs = firmware(ROOTFS_EXT4).read_bytes()
    board, layout = a_host_with_opensbi(
        firmware,
        LINUX_BIN,
        virtio=Virtio(blocks=len(rootfs) // SECTOR),
        bootargs=BOOTARGS,
    )
    board.virtio.blk.load(rootfs)
    loaded_by_python(board, layout, firmware)
    prompted = run_to_the_prompt(board)
    assert prompted, (
        "Linux never prompted. OpenSBI's console:\n"
        f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
        f"{plain(board.virtio.console.output)[-3000:]}"
    )
    return board


@pytest.mark.platform
class TestWhenLinuxBootsTheQuickWay:
    def test_it_says_its_version_through_opensbi_and_prompts_on_its_console(
        self, linux_at_its_prompt
    ):
        # 🎓 The kernel's first words go through OpenSBI's console on the
        # 16550 (`earlycon=sbi`), before it has found a console of its own;
        # once 🎭 the virtio console is up, everything goes there.
        board = linux_at_its_prompt
        early = plain(board.uart.output)
        console = plain(board.virtio.console.output)

        assert BANNER.search(early), f"No version. OpenSBI's console:\n{early}"
        assert PROMPT.search(console), f"No prompt. The console:\n{console}"


@pytest.mark.platform
class TestWhenPythonTypesAtLinuxsShell:
    def test_uname_names_linux_and_the_pinned_kernel(self, linux_at_its_prompt):
        board = linux_at_its_prompt

        answer = type_and_wait_for_the_prompt(board, "uname -a")

        pinned = tomllib.loads(VERSIONS.read_text())["linux"]["version"]
        assert answer.startswith(f"Linux socpuppet {pinned} ")
        assert " riscv64 Linux" in answer


@pytest.mark.platform
class TestWhenPythonTypesPoweroff:
    def test_the_system_controller_switches_the_cpu_off(
        self, linux_at_its_prompt
    ):
        # 🎓 `poweroff` goes to the kernel's `syscon-poweroff` driver, which
        # writes the system controller's register, as OpenSBI's test payload
        # did by asking OpenSBI.
        board = linux_at_its_prompt
        board.virtio.console.write("poweroff\n")

        gone = board.platform.run_until(
            lambda: switched_off(board), timeout=SWITCHES_OFF_WITHIN
        )

        # ⚠️ Not the kernel's own last line, "reboot: Power down": 🎭 the
        # system controller switches the CPU off the moment the register
        # is written, before the virtio console's queue has carried it.
        assert gone, (
            f"Not switched off. The console:\n{plain(board.virtio.console.output)}"
        )
