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


@pytest.mark.platform
class TestWhenFirmwarePrintsThroughTheUart:
    def test_the_uarts_output_is_what_it_printed(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.DbtRiseCpu(xlen=64, reset_vector=RAM_BASE))
        bus = platform.add("bus", sp.Router())
        ram = platform.add("ram", sp.Memory(size=0x1000))
        uart = platform.add("uart", sp.Ns16550())
        platform.connect(cpu.socket, bus.target)
        bus.map(ram.socket, base=RAM_BASE)
        bus.map(uart.socket, base=UART_BASE)
        platform.build()
        platform.poke(RAM_BASE, PRINT_OK_THEN_SLEEP)

        # Seven instructions: ten microseconds is far more than they need.
        platform.run(sp.us(10))

        assert uart.output == "OK"
