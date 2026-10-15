"""The APLIC in a platform: a device's line comes in and a message goes out."""

import pytest

import socpuppet as sp

APLIC_BASE = 0x0C00_0000
UART_BASE = 0x1000_0000
# Where the test has messages sent. A RAM is there, so that what arrived
# can be read back: on a real platform it is the page of the CPU's IMSIC.
PAGE = 0x2400_0000

# The source the UART's line is at, and the identity it is given. They need
# not be the same number.
SOURCE = 16
IDENTITY = 40


def set_up_the_aplic_and_the_uart():
    """What firmware does: the APLIC first, and then the device."""
    # Where messages go, as a page number.
    yield sp.write32(APLIC_BASE + 0x1BC0, PAGE >> 12)
    yield from set_up_the_rest()


def set_up_the_rest():
    """What firmware does when it need not say where messages go."""
    # The domain's interrupts on.
    yield sp.write32(APLIC_BASE + 0x0000, 1 << 8)
    # The source asks while its line is high, sends IDENTITY, and is enabled.
    yield sp.write32(APLIC_BASE + 4 * SOURCE, 6)
    yield sp.write32(APLIC_BASE + 0x3000 + 4 * SOURCE, IDENTITY)
    yield sp.write32(APLIC_BASE + 0x1EDC, SOURCE)
    # The UART interrupts when a byte has come in.
    yield sp.write(UART_BASE + 1, b"\x01")


def a_uart_at_an_aplic(script=set_up_the_aplic_and_the_uart, **described):
    """A UART whose line goes to an APLIC, set up by a stand-in for a CPU.

    `script` is what the stand-in does, and the APLIC is described with
    what `described` says. Returns the platform and the UART.
    """
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    aplic = platform.add("aplic", sp.Aplic(**described))
    uart = platform.add("uart", sp.Ns16550())
    page = platform.add("page", sp.Memory(size=0x1000))
    platform.connect(cpu.socket, bus.target)
    bus.map(aplic.socket, base=APLIC_BASE)
    bus.map(uart.socket, base=UART_BASE)
    bus.map(page.socket, base=PAGE)
    platform.connect(uart.irq, aplic.source16)
    # The APLIC's messages go onto the same bus as a second source of
    # accesses, beside the CPU.
    platform.connect(aplic.msi, bus.add_input())
    platform.build()
    return platform, uart


@pytest.mark.platform
class TestWhenADeviceAtAnAplicsSourceInterrupts:
    def test_the_sources_identity_is_written_to_the_page(self):
        platform, uart = a_uart_at_an_aplic()
        platform.run(sp.us(1))

        uart.write("A")
        platform.run(sp.us(1))

        assert platform.peek32(PAGE) == IDENTITY


@pytest.mark.platform
class TestWhenADeviceAtAnAplicsSourceIsQuiet:
    def test_nothing_is_written_to_the_page(self):
        platform, _ = a_uart_at_an_aplic()

        platform.run(sp.us(1))

        assert platform.peek32(PAGE) == 0


@pytest.mark.platform
class TestWhenAnAplicIsDescribedWithWhereItsMessagesGo:
    """🎓 For a platform whose firmware never says, as OpenSBI and Linux
    do not for an APLIC that serves supervisor mode alone."""

    def test_a_source_that_fires_writes_there_with_nothing_written_to_say_so(
        self,
    ):
        platform, uart = a_uart_at_an_aplic(set_up_the_rest, messages_to=PAGE)
        platform.run(sp.us(1))

        uart.write("A")
        platform.run(sp.us(1))

        assert platform.peek32(PAGE) == IDENTITY


class TestWhenAnAplicIsDescribedWithAnAddressThatIsNotAPage:
    def test_it_is_refused_and_the_error_says_what_a_page_is(self):
        with pytest.raises(ValueError, match="4 KiB"):
            sp.Aplic(messages_to=PAGE + 4)
