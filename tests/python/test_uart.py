"""The UART, as firmware and a Python test see it."""

import pytest

import socpuppet as sp

RAM_BASE = 0x8000_0000
UART_BASE = 0x1000_0000

# A program in RISC-V machine code that prints "OK" and then sleeps. It
# expects the UART at UART_BASE.
PRINT_OK_THEN_SLEEP = b"".join(
    word.to_bytes(4, "little")
    for word in (
        0x100002B7,  # lui   t0, 0x10000        t0 = UART_BASE
        0x04F00313,  # li    t1, 'O'
        0x00628023,  # sb    t1, 0(t0)          the transmit register
        0x04B00313,  # li    t1, 'K'
        0x00628023,  # sb    t1, 0(t0)
        0x10500073,  # wfi                      sleep until an interrupt
        0xFFDFF06F,  # j     -4                 and sleep again if one comes
    )
)


def a_cpu_running(program, *, interrupted_by_the_uart=False):
    """A CPU, a RAM that holds `program` and a UART, built.

    Returns the platform and the UART.
    """
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.DbtRiseCpu(xlen=64, reset_vector=RAM_BASE))
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=0x1000))
    uart = platform.add("uart", sp.Ns16550())
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(uart.socket, base=UART_BASE)
    if interrupted_by_the_uart:
        # Straight to the CPU, with no interrupt controller between: with
        # one device there is nothing to tell apart.
        platform.connect(uart.irq, cpu.irq)
    platform.build()
    platform.poke(RAM_BASE, program)
    return platform, uart


@pytest.mark.platform
class TestWhenFirmwarePrintsThroughTheUart:
    def test_the_uarts_output_is_what_it_printed(self):
        platform, uart = a_cpu_running(PRINT_OK_THEN_SLEEP)

        # Seven instructions: ten microseconds is far more than they need.
        platform.run(sp.us(10))

        assert uart.output == "OK"


# A program that sends back whatever comes in: it waits for the UART's line
# status to say a byte is ready, reads the byte and transmits it, for ever.
ECHO = b"".join(
    word.to_bytes(4, "little")
    for word in (
        0x100002B7,  # lui   t0, 0x10000        t0 = UART_BASE
        0x0052C303,  # lbu   t1, 5(t0)          the line status
        0x00137313,  # andi  t1, t1, 1          its "data ready" bit
        0xFE030CE3,  # beqz  t1, -8             not yet: look again
        0x0002C303,  # lbu   t1, 0(t0)          the receive register
        0x00628023,  # sb    t1, 0(t0)          the transmit register
        0xFEDFF06F,  # j     -20                and wait for the next
    )
)


@pytest.mark.platform
class TestWhenPythonTypesAtAUart:
    def test_firmware_receives_what_was_typed(self):
        platform, uart = a_cpu_running(ECHO)

        uart.write("spam\n")
        # Five bytes at six instructions each: a hundred microseconds is
        # far more than they need.
        platform.run(sp.us(100))

        assert uart.output == "spam\n"

    def test_what_is_typed_between_two_runs_is_received_in_the_second(self):
        # As a script does that waits for a prompt before it answers.
        platform, uart = a_cpu_running(ECHO)
        platform.run(sp.us(100))

        uart.write("eggs\n")
        platform.run(sp.us(100))

        assert uart.output == "eggs\n"


# A program that sends back whatever comes in, and sleeps until something
# does: it has the UART interrupt when a byte is waiting, and its handler
# reads the byte and transmits it.
ECHO_FROM_AN_INTERRUPT = b"".join(
    word.to_bytes(4, "little")
    for word in (
        0x100002B7,  # lui   t0, 0x10000        t0 = UART_BASE
        0x00000317,  # auipc t1, 0              t1 = where this is
        0x02830313,  # addi  t1, t1, 40         the handler, below
        0x30531073,  # csrw  mtvec, t1          traps go there
        0x00100313,  # li    t1, 1              "a received byte waits"
        0x006280A3,  # sb    t1, 1(t0)          the interrupt enable register
        0x00B31313,  # slli  t1, t1, 11         the external interrupt
        0x30432073,  # csrs  mie, t1            enable it
        0x30046073,  # csrsi mstatus, 8         and interrupts as a whole
        0x10500073,  # wfi                      sleep until an interrupt
        0xFFDFF06F,  # j     -4                 and sleep again after it
        0x0002C303,  # lbu   t1, 0(t0)          handler: the receive register
        0x00628023,  # sb    t1, 0(t0)          the transmit register
        0x30200073,  # mret                     back to sleep
    )
)


@pytest.mark.platform
class TestWhenFirmwareSleepsUntilTheUartInterrupts:
    def test_it_receives_what_was_typed(self):
        platform, uart = a_cpu_running(
            ECHO_FROM_AN_INTERRUPT, interrupted_by_the_uart=True
        )

        uart.write("spam\n")
        # Eleven instructions to set up and three a byte: a hundred
        # microseconds is far more than they need.
        platform.run(sp.us(100))

        assert uart.output == "spam\n"

    def test_it_stays_asleep_while_nothing_is_typed(self):
        platform, uart = a_cpu_running(
            ECHO_FROM_AN_INTERRUPT, interrupted_by_the_uart=True
        )

        platform.run(sp.us(100))

        assert uart.output == ""


@pytest.mark.platform
class TestWhenPythonReadsWhatIsNewOnTheUart:
    def test_from_inside_a_character_it_gets_the_rest_of_the_bytes_as_they_are(
        self,
    ):
        # As a terminal does that shows each byte once, and may have read
        # to the middle of a character.
        platform, uart = a_cpu_running(ECHO)
        uart.write(b"spam \xc3\xa9\n")  # "é" is the two bytes C3 A9
        # Eight bytes at six instructions each: a hundred microseconds is
        # far more than they need.
        platform.run(sp.us(100))

        assert uart.output_since(6) == b"\xa9\n"
