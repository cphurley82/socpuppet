"""🧵 QEMU's log of what QBox's CPU ran, as a list of addresses.

🎓 QEMU translates a block of instructions at a time, and logs each block
as it is about to run it, when asked to through its debugger:

    (gdb) monitor logfile /tmp/trace.log
    (gdb) monitor one-insn-per-tb on
    (gdb) monitor log exec,nochain

`one-insn-per-tb` makes every block one instruction long, so the log has
a line for each instruction, and `nochain` stops QEMU from going from one
block to the next without logging it. A block can be stopped before it
runs, and QEMU says so on a line of its own; it is then logged again when
it does run.

`pcs` reads the addresses out, one for each instruction that ran, so that
two runs can be compared and the first instruction where they part found.
"""

import re

#: A block about to run: "Trace <cpu>: <host address> [<cs_base>/<pc>/
#: <flags>/<cflags>]", the pc in hexadecimal.
_RAN = re.compile(r"^Trace \d+: \S+ \[[0-9a-f]+/([0-9a-f]+)/", re.MULTILINE)
#: A block stopped before it ran: "Stopped execution of TB chain before
#: <host address> [<pc>]".
_STOPPED = re.compile(
    r"^Stopped execution of TB chain before \S+ \[([0-9a-f]+)\]"
)


def pcs(log: str) -> list[int]:
    """The address of each instruction QEMU's log says ran, in order.

    `log` is the log's text, written with `exec` and `nochain`, and with
    one instruction to a block.
    """
    ran: list[int] = []
    for line in log.splitlines():
        if found := _RAN.match(line):
            ran.append(int(found[1], 16))
        elif (
            (stopped := _STOPPED.match(line))
            and ran
            and ran[-1] == int(stopped[1], 16)
        ):
            ran.pop()
    return ran


__all__ = ["pcs"]
