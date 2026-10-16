"""M28's exit test: UEFI boots on OpenSBI, to a shell Python types at.

🧦 EDK2 is UEFI, the firmware a server's kernel is loaded by. Its RISC-V
port runs in supervisor mode as OpenSBI's next stage, where a kernel
would be, and is the first program here not written for the puppet that
turns paging on, takes the timer's interrupt in supervisor mode, and
reads the devicetree whole. It says what each of its drivers does as it
loads, counts down twice on the timer, once for its boot manager and once
for its shell, and stops at `Shell>`.

🎭 The quick way: Python puts `fw_jump`, EDK2 and the devicetree in RAM
where `fw_jump` expects them, and QEMU's reset vector in the ROM hands
`fw_jump` the hart's number and the devicetree's address, as in M23.
"""

import re
from typing import NamedTuple

import pytest

import socpuppet as sp
from cast import FW_JUMP_BIN, UEFI_FD
from devicetree_compiler import needs_dtc
from socpuppet import devicetree, opensbi
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.host import RAM_BASE, host

#: OpenSBI is handed the devicetree compiled, and dtc compiles it.
pytestmark = needs_dtc

PROMPT = "Shell>"
#: What EDK2's paging library says once `satp` has kept what it wrote.
PAGING_ON = re.compile(r"SATP mode \d+ successfully configured")
#: The boot manager's countdown, and then the shell's, each with how many
#: seconds it waits for a key.
BOOT_MANAGERS_COUNTDOWN = re.compile(r"Press ESCAPE within (\d+) seconds")
SHELLS_COUNTDOWN = re.compile(r"Press ESC in (\d+) seconds")
#: QBox's hart reaches the prompt in about 90 s of its time and the
#: interpreter in about 60: SEC unpacks the rest of EDK2, 6 MB compressed
#: with LZMA, for 25 to 40 s of it, and the two countdowns wait 10 s.
LONG_ENOUGH = sp.ms(150_000)


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
    board = host(boot=from_rom, sbi=True)
    layout = opensbi.lay_out(
        firmware(FW_JUMP_BIN).read_bytes(),
        firmware(UEFI_FD).read_bytes(),
        devicetree.compile(
            board.platform.devicetree(dialect="linux", model="socpuppet host")
        ),
        ram=RAM_BASE,
    )
    board.platform.build()
    opensbi.load(board.platform, layout, rom=ROM_BASE, via=board.cpu.socket)
    board.platform.run_until(
        lambda: BOOT_MANAGERS_COUNTDOWN.search(board.uart.output),
        timeout=LONG_ENOUGH,
    )
    countdown_began = board.platform.time
    board.platform.run_until(
        lambda: PROMPT in board.uart.output, timeout=LONG_ENOUGH
    )
    return AtItsShell(board, countdown_began)


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


def plain(console):
    """`console` without the escape sequences a UEFI terminal moves and
    colours with."""
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", console)


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
