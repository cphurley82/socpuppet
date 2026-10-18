"""Python at the keyboard of UEFI's shell, on 🎭 the host.

The UEFI boot's exit test, `test_m28_exit.py`, brought UEFI to `Shell>`;
these are its ways of getting
there and of typing at it, for every test that boots UEFI.
"""

import re

import socpuppet as sp
from console import plain

PROMPT = "Shell>"
#: The boot manager's countdown, and then the shell's, each with how many
#: seconds it waits for a key.
BOOT_MANAGERS_COUNTDOWN = re.compile(r"Press ESCAPE within (\d+) seconds")
SHELLS_COUNTDOWN = re.compile(r"Press ESC in (\d+) seconds")
#: QBox's hart reaches the prompt in about 90 s of its time and the
#: interpreter in about 65: SEC unpacks the rest of EDK2, 6 MB compressed
#: with LZMA, for 25 to 40 s of it, and the two countdowns wait 10 s. From
#: the flash the boot ROM's check of the image comes first, which is about
#: 4 s for each 2 MiB.
LONG_ENOUGH = sp.ms(150_000)
#: The slowest command typed here is `memmap`, which takes 28 s of QBox's
#: time to give its hundred and fifty rows, and 22 s of the interpreter's.
ANSWERS_WITHIN = sp.ms(60_000)


def run_to_the_prompt(board, *, within=LONG_ENOUGH):
    """Run until UEFI's shell prompts, or for `within` of simulated time.

    Gives whether it prompted.
    """
    return board.platform.run_until(
        lambda: PROMPT in board.uart.output, timeout=within
    )


def type_and_wait_for_the_prompt(board, command, *, meanwhile=None):
    """Type `command` and Enter at the shell, and run until it prompts again.

    `meanwhile`, if given, is called each time the run stops to look for
    the prompt, which is each time simulated time is about to move on: a
    script's chance to answer what the firmware has done. Gives what the
    shell said in between, as plain text.
    """
    said_before = len(board.uart.output)
    board.uart.write(command + "\r")

    def prompted_again():
        if meanwhile is not None:
            meanwhile()
        return PROMPT in plain(board.uart.output[said_before:])

    prompted = board.platform.run_until(prompted_again, timeout=ANSWERS_WITHIN)
    assert prompted, f"The shell did not prompt again after {command!r}"
    return plain(board.uart.output[said_before:])
