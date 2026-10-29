"""UEFI boots on OpenSBI, to a shell Python types at.

🧦 EDK2 is UEFI, the firmware a server's kernel is loaded by. Its RISC-V
port runs in supervisor mode as OpenSBI's next stage, where a kernel
would be, and is the first program here not written for the puppet that
turns paging on, takes the timer's interrupt in supervisor mode, and
reads the devicetree whole. It says what each of its drivers does as it
loads, counts down twice on the timer, once for its boot manager and once
for its shell, and stops at `Shell>`.

It boots both ways test_opensbi_boots.py does (`opensbi_boots`): the quick way,
with Python as the stage before, and from the flash, as silicon does.

🧵 Python is the keyboard at the console, as at Zephyr's shell
(test_zephyr_shell.py).
"""

import re
from typing import NamedTuple

import pytest

import socpuppet as sp
from cast import UEFI_FD
from console import plain
from devicetree_compiler import needs_dtc
from opensbi_boots import a_host_with_opensbi, in_the_flash, loaded_by_python
from socpuppet.boards.host import RAM_BASE, RAM_SIZE
from uefi_shell import (
    BOOT_MANAGERS_COUNTDOWN,
    LONG_ENOUGH,
    PROMPT,
    SHELLS_COUNTDOWN,
    type_and_wait_for_the_prompt,
)

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. Each
#: boot of UEFI takes seconds, so the tests are handed out first.
pytestmark = [needs_dtc, pytest.mark.long]

#: What EDK2's paging library says once `satp` has kept what it wrote.
PAGING_ON = re.compile(r"SATP mode \d+ successfully configured")
#: What the boot ROM says when it starts an image from the flash.
ROMS_LINE = re.compile(r"rom: \S+: \d+ bytes to ")
#: After a reset the ROM copies the image again, a little over 4 MiB, and
#: checks it a byte at a time before it says its line: about 9 s, at the
#: 4 s for each 2 MiB, as OpenSBI's boot from the flash takes.
REBOOTS_WITHIN = sp.ms(20_000)


class AtItsShell(NamedTuple):
    """A host whose UEFI has stopped at its prompt."""

    board: object
    #: The CPU's time when the boot manager began its countdown.
    countdown_began: int


@pytest.fixture
def uefi_at_its_shell(firmware):
    """A host that has booted OpenSBI and EDK2 the quick way, to `Shell>`.

    Or for `LONG_ENOUGH`, if the prompt never comes.
    """
    board, layout = a_host_with_opensbi(firmware, UEFI_FD)
    loaded_by_python(board, layout, firmware)
    board.platform.run_until(
        lambda: BOOT_MANAGERS_COUNTDOWN.search(board.uart.output),
        timeout=LONG_ENOUGH,
    )
    countdown_began = board.platform.time
    board.platform.run_until(
        lambda: PROMPT in board.uart.output, timeout=LONG_ENOUGH
    )
    return AtItsShell(board, countdown_began)


@pytest.mark.representative("uefi")
@pytest.mark.platform
class TestWhenUefiBootsTheQuickWay:
    def test_it_turns_paging_on_and_counts_down_on_the_timer_to_its_prompt(
        self, uefi_at_its_shell
    ):
        board, countdown_began = uefi_at_its_shell
        console = plain(board.uart.output)

        assert in_order(
            console,
            PAGING_ON,
            BOOT_MANAGERS_COUNTDOWN,
            SHELLS_COUNTDOWN,
            PROMPT,
        )
        assert board.platform.time - countdown_began >= promised_wait(console)


@pytest.mark.platform
class TestWhenPythonTypesAtUefisShell:
    def test_ver_names_edk2_and_memmap_maps_the_ram_the_devicetree_gave(
        self, uefi_at_its_shell
    ):
        board, _ = uefi_at_its_shell

        version = type_and_wait_for_the_prompt(board, "ver")
        memory_map = type_and_wait_for_the_prompt(board, "memmap")

        assert re.search(r"UEFI v2\.\d+ \(EDK II, ", version)
        assert span(memory_map) == (RAM_BASE, RAM_BASE + RAM_SIZE)


@pytest.mark.platform
class TestWhenUefiBootsFromTheFlash:
    def test_the_rom_starts_it_and_reset_at_the_prompt_starts_the_rom_again(
        self, firmware
    ):
        board, layout = a_host_with_opensbi(firmware, UEFI_FD)
        in_the_flash(board, layout, firmware)
        board.platform.run_until(
            lambda: PROMPT in board.uart.output, timeout=LONG_ENOUGH
        )

        board.uart.write("reset\r")
        board.platform.run_until(
            lambda: len(ROMS_LINE.findall(board.uart.output)) == 2,
            timeout=REBOOTS_WITHIN,
        )

        assert in_order(plain(board.uart.output), ROMS_LINE, PROMPT, ROMS_LINE)


def span(memory_map):
    """Where the first region in `memory_map` starts and the last one ends.

    `memmap` gives a row to each region, with its type, its first address
    and its last, in hex.
    """
    regions = [
        (int(first, 16), int(last, 16) + 1)
        for first, last in re.findall(
            r"^\S+\s+([0-9A-F]{16})-([0-9A-F]{16}) ", memory_map, re.MULTILINE
        )
    ]
    return min(first for first, _ in regions), max(end for _, end in regions)


def in_order(text, *expected):
    """Whether each of `expected`, a string or a pattern, is in `text`
    after the one before it."""
    at = 0
    for each in expected:
        found = re.compile(re.escape(each) if isinstance(each, str) else each)
        match = found.search(text, at)
        if match is None:
            return False
        at = match.end()
    return True


def promised_wait(console):
    """The CPU's time the two countdowns in `console` say they wait."""
    return sp.ms(
        1000
        * sum(
            longest(countdown, console)
            for countdown in (BOOT_MANAGERS_COUNTDOWN, SHELLS_COUNTDOWN)
        )
    )


def longest(countdown, console):
    """The most seconds `countdown` says, in `console`.

    The shell says its question again each second, a second less each time.
    """
    return max(int(each) for each in countdown.findall(console))
