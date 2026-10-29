"""🧦 Python types at the host's shell, and the shell answers.

The host runs Zephyr's shell. Python is the other end of the serial line:
`uart.write` is the keyboard and `uart.output` is the screen. 🧵 That is
the whole of a terminal, and a script can hold it as well as a person.

What makes it more than a parlour trick is how the keystrokes are heard.
The UART is on the IO die and the CPU on the compute die, with a link
between them that carries transactions and no wires. So the UART's
interrupt line stops at an APLIC beside it, which writes a message across
the link to the CPU's IMSIC (see socpuppet/boards/host.py). The example
counts those messages at the end.

Build the firmware first:      uv run firmware/build.py
Run it:                        python examples/shell_from_python.py

The image is looked for in build/firmware, or in SOCPUPPET_FIRMWARE_DIR if
that is set. With no image there the example says so and counts as not
run, unless SOCPUPPET_REQUIRE_FIRMWARE is set, as it is in CI, where a
missing image is a failure.
"""

import os
import sys

import socpuppet as sp
from socpuppet.boards.host import IMSIC_BASE, UART_SOURCE, host
from socpuppet.run import firmware_directory

IMAGE = firmware_directory() / "shell_module_socpuppet_host.elf"
PROMPT = "uart:~$ "
#: What to type, and something each answer has in it.
COMMANDS = (
    ("kernel version", "Zephyr version"),
    ("kernel uptime", "Uptime:"),
    ("device list", "devices:"),
)
#: Far more simulated time than the shell needs for a line.
LONG_ENOUGH = sp.ms(200)


def console_interrupts(board):
    """How many times the console has interrupted, each time as a message.

    A message is a write of the identity the UART's source sends, to the
    page of the CPU's IMSIC, and the trace has it as it crossed the link.
    """
    return sum(
        1
        for each in board.platform.trace
        if each.source == board.link.b.peer_initiator.path
        and each.command == "write"
        and each.address == IMSIC_BASE
        and int.from_bytes(each.data, "little") == UART_SOURCE
    )


def answered(board, shown, answer):
    """Whether the shell has said `answer` since `shown`, and prompted again.

    The prompt is looked for after the answer and not at the console's end:
    the shell switches to green before its prompt and back after it, so a
    prompt is never the last thing it prints.
    """
    _, found, after = board.uart.output[shown:].partition(answer)
    return bool(found) and PROMPT in after


if __name__ == "__main__":
    if not IMAGE.exists():
        missing = (
            f"There is no {IMAGE} yet. Build the firmware with "
            "`uv run firmware/build.py`, which takes a few minutes the "
            "first time."
        )
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            sys.exit(missing)
        print(missing)
        # ctest's code for "could not be run here", which is not a failure.
        sys.exit(77)

    board = host(trace=True)
    board.platform.build()
    board.platform.load_elf(IMAGE)

    if not board.platform.run_until(
        lambda: PROMPT in board.uart.output, timeout=LONG_ENOUGH
    ):
        sys.exit("❌ The shell never prompted.")

    for command, answer in COMMANDS:
        shown = len(board.uart.output)
        board.uart.write(command + "\n")
        if not board.platform.run_until(
            lambda shown=shown, answer=answer: answered(board, shown, answer),
            timeout=LONG_ENOUGH,
        ):
            print(board.uart.output, end="")
            sys.exit(f"\n❌ The shell did not answer `{command}`.")

    print(board.uart.output)
    elapsed = board.platform.time / sp.ms(1)
    print(
        f"\n✅ The shell answered {len(COMMANDS)} commands in {elapsed:.1f} ms "
        f"of simulated time. The console interrupted "
        f"{console_interrupts(board)} times, each as a message from the IO "
        f"die's APLIC and none on a wire."
    )
