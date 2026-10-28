"""A shell that answers Python.

The host runs Zephyr's shell, and Python is at the other end of the
serial line: it types a command and reads the answer. A shell wants to be
woken when something is typed, so the console interrupts, and the UART is
on the IO die, with no wire to the CPU. Its line goes as far as the APLIC
beside it, which sends a message across the die-to-die link to the CPU's
IMSIC. (A shell whose console cannot interrupt polls it, and answers all
the same, which is why one test here looks for the messages.)

So every interrupt the host takes but its timer's is a message now: the
console's here, and the drive's in the disk test
(test_zephyr_disk_on_the_host.py), which runs on the same board.

The image is `samples/subsys/shell/shell_module` for `socpuppet_host`, as
`firmware/build.py` builds it, with nothing of socpuppet's in the
application.
"""

import functools

import pytest

import socpuppet as sp
from cast import SHELL, SHELL_PROMPT, SHELL_VERSION, boot
from link_trace import sent_to_the_compute_die
from socpuppet.boards.host import IMSIC_BASE, UART_SOURCE, host
from socpuppet.boards.manager import add_manager, scripted_manager

#: Zephyr starts in a millisecond or two, and the shell answers a line in
#: less. This leaves room and still ends a run that never answers.
LONG_ENOUGH = sp.ms(200)


def a_host_running_the_shell(firmware, **described):
    """The host with Zephyr's shell loaded, run until the shell prompts."""
    board = host(**described)
    boot(board, firmware, host=SHELL)
    board.platform.run_until(
        lambda: SHELL_PROMPT in board.uart.output, timeout=LONG_ENOUGH
    )
    return board


def type_and_wait_for(board, typed, answer):
    """Type `typed` at the host's console and run until `answer` is printed."""
    board.uart.write(typed)
    board.platform.run_until(
        lambda: answer in board.uart.output, timeout=LONG_ENOUGH
    )


def console_interrupts(board):
    """The console's interrupts, as they crossed to the compute die.

    Each is a write of the identity the UART's source sends, to the page of
    the CPU's IMSIC.
    """
    return [
        each
        for each in sent_to_the_compute_die(board)
        if each.command == "write"
        and each.address == IMSIC_BASE
        and int.from_bytes(each.data, "little") == UART_SOURCE
    ]


@pytest.mark.platform
class TestWhenTheHostRunsZephyrsShell:
    def test_it_prompts(self, firmware):
        board = a_host_running_the_shell(firmware)

        assert SHELL_PROMPT in board.uart.output


@pytest.mark.platform
class TestWhenPythonTypesACommandAtTheHostsShell:
    def test_the_shell_answers_it(self, firmware):
        board = a_host_running_the_shell(firmware)

        type_and_wait_for(board, "kernel version\n", SHELL_VERSION)

        assert SHELL_VERSION in board.uart.output

    def test_the_shell_echoes_what_was_typed_as_a_terminal_expects(
        self, firmware
    ):
        board = a_host_running_the_shell(firmware)
        before = len(board.uart.output)

        type_and_wait_for(board, "kernel version\n", SHELL_VERSION)

        assert "kernel version" in board.uart.output[before:]

    def test_the_console_interrupts_the_cpu_meanwhile_with_messages_from_the_io_die(
        self, firmware
    ):
        # A shell can also poll its UART, and would answer just the same.
        # This one is interrupted, to hear and to speak: by a message for
        # each time the UART's line rose, and no wire.
        board = a_host_running_the_shell(firmware, trace=True)
        before = len(console_interrupts(board))

        type_and_wait_for(board, "kernel version\n", SHELL_VERSION)

        assert len(console_interrupts(board)) > before

    def test_a_second_command_is_answered_too(self, firmware):
        # The console is still listening after its handler has run for a
        # received byte and for room to transmit, in whatever order they
        # came.
        board = a_host_running_the_shell(firmware)
        type_and_wait_for(board, "kernel version\n", SHELL_VERSION)
        answered = len(board.uart.output)

        type_and_wait_for(board, "kernel uptime\n", "Uptime:")

        assert "Uptime:" in board.uart.output[answered:]


@pytest.mark.platform
class TestWhenPythonTypesTwoCommandsAtOnce:
    def test_both_are_answered(self, firmware):
        board = a_host_running_the_shell(firmware)

        board.uart.write("kernel version\nkernel uptime\n")
        board.platform.run_until(
            lambda: "Uptime:" in board.uart.output, timeout=LONG_ENOUGH
        )

        assert SHELL_VERSION in board.uart.output
        assert "Uptime:" in board.uart.output


@pytest.mark.platform
class TestWhenPythonTypesWhileTheShellIsStillPrinting:
    def test_what_it_typed_is_answered_too(self, firmware):
        # The UART then has a byte waiting and room to transmit at once.
        # Its handler sees to one, and the line stays high for the other,
        # with no edge for the APLIC to send a message on. The module has
        # the APLIC look again after each handler.
        board = a_host_running_the_shell(firmware)
        shown = len(board.uart.output)
        board.uart.write("kernel version\n")
        # The echo has begun, and the answer has not.
        board.platform.run_until(
            lambda: "kernel" in board.uart.output[shown:], timeout=LONG_ENOUGH
        )
        still_printing = SHELL_VERSION not in board.uart.output

        board.uart.write("kernel uptime\n")
        board.platform.run_until(
            lambda: "Uptime:" in board.uart.output, timeout=LONG_ENOUGH
        )

        assert still_printing
        assert SHELL_VERSION in board.uart.output
        assert "Uptime:" in board.uart.output


@pytest.mark.platform
class TestWhenTheHostsShellIsAcrossTheRealLink:
    def test_it_answers_and_its_console_interrupts_by_messages_over_the_link(
        self, firmware
    ):
        # 🎭 A script trains the link and lets the host go, as in
        # test_host_across_the_real_link.py. The APLIC's registers are then
        # written across the trained link, and its messages come back over it.
        board = a_host_running_the_shell(
            firmware,
            manager=functools.partial(
                add_manager, script=scripted_manager().script
            ),
            trace=True,
        )
        before = len(console_interrupts(board))

        type_and_wait_for(board, "kernel version\n", SHELL_VERSION)

        assert SHELL_VERSION in board.uart.output
        assert len(console_interrupts(board)) > before
