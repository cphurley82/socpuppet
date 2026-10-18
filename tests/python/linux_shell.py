"""Python at the keyboard of Linux's shell, on 🎭 the host.

The Linux boot's exit test, `test_m20_exit.py`, brings a kernel to its
prompt on the virtio console; these are its ways of waiting for the prompt
and of typing at it, for every test that boots Linux.
"""

import re

import socpuppet as sp
from console import plain

#: How a busybox shell that is logged in as root prompts on the host, by
#: Alpine's /etc/profile: the host's name, the directory, and a hash.
PROMPT = re.compile(r"socpuppet:\S+# $")
#: What the kernel is told: its console is 🎭 the virtio console, its early
#: messages go through OpenSBI's console until that is up, and its root
#: filesystem is 🎭 the virtio disk, writable.
BOOTARGS = "console=hvc0 earlycon=sbi root=/dev/vda rw"
#: The prompt comes at 208 s of the CPU's time on QBox's hart, 6 s on the
#: wall, and 75 s on the wall on the interpreter: a stock kernel's own
#: initcalls are most of it, the tracing subsystem's tens of seconds among
#: them.
LONG_ENOUGH = sp.ms(400_000)
#: How long a command typed at the prompt may take to prompt again: `uname`
#: answers in under a second of the CPU's time.
ANSWERS_WITHIN = sp.ms(10_000)
#: How long `poweroff` may take to reach the system controller: busybox
#: stops every process and unmounts the disk first, a second or two of the
#: CPU's time.
SWITCHES_OFF_WITHIN = sp.ms(30_000)


def run_to_the_prompt(board, *, within=LONG_ENOUGH):
    """Run until Linux's shell prompts, or for `within` of simulated time.

    Gives whether it prompted.
    """
    return board.platform.run_until(
        lambda: PROMPT.search(plain(board.virtio.console.output)),
        timeout=within,
    )


def type_and_wait_for_the_prompt(board, command):
    """Type `command` and Enter at the shell, and run until it prompts again.

    Gives what the shell said in between, as plain text, without the
    command's own echo.
    """
    console = board.virtio.console
    said_before = len(console.output)
    console.write(command + "\n")
    prompted = board.platform.run_until(
        lambda: PROMPT.search(plain(console.output[said_before:])),
        timeout=ANSWERS_WITHIN,
    )
    assert prompted, f"The shell did not prompt again after {command!r}"
    return plain(console.output[said_before:]).partition("\n")[2]
