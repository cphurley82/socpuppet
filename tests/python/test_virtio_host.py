"""🧵 Python as the first driver of a virtio device.

The platform tests run the driver against the entropy device, the smallest
virtio device there is, and the console, on a scripted host; the rest play
it against a fake device with no simulator at all.

    host ─▶ bus ─┬─▶ ram
     ▲      ▲    └─▶ device.cpu
     │      └──────── device.dma
     └─────────────── device.irq
"""

import pytest

import socpuppet as sp
from scripts import play
from socpuppet.regs import virtio_mmio as regs

RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
DEVICE_BASE = 0x1000_1000

VERSION_1 = 1 << 32


def host_with(script, device):
    """A scripted host with a RAM and one virtio `device`, built.

    Returns the platform and the device at its place.
    """
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=RAM_SIZE))
    placed = platform.add("device", device)
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(placed.cpu, base=DEVICE_BASE)
    platform.connect(placed.dma, bus.add_input())
    platform.connect(placed.irq, cpu.irq)
    platform.build()
    return platform, placed


@pytest.mark.platform
class TestWhenTheHostAsksTheEntropyDeviceForBytesTwice:
    def test_it_gets_as_many_as_it_asked_each_time_and_not_the_same_ones(self):
        answers = []

        def script():
            rng = sp.VirtioRngHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from rng.start()
            answers.append((yield from rng.read(32)))
            answers.append((yield from rng.read(32)))

        platform, _ = host_with(script, sp.VirtioRng())

        platform.run()

        assert [len(answer) for answer in answers] == [32, 32]
        assert answers[0] != answers[1]
        assert answers[0] != bytes(32)


@pytest.mark.platform
class TestWhenTheHostSendsThroughTheConsole:
    def test_python_reads_it_as_the_consoles_output(self):
        def script():
            console = sp.VirtioConsoleHost(
                registers=DEVICE_BASE, memory=RAM_BASE
            )
            yield from console.start()
            yield from console.send(b"spam")
            yield from console.send(b" and eggs")

        platform, console = host_with(script, sp.VirtioConsole())

        platform.run()

        assert console.output == "spam and eggs"


@pytest.mark.platform
class TestWhenPythonTypesAtTheConsoleWhileTheHostWaitsForBytes:
    def test_the_host_receives_what_was_typed(self):
        received = []

        def script():
            console = sp.VirtioConsoleHost(
                registers=DEVICE_BASE, memory=RAM_BASE
            )
            yield from console.start()
            received.append((yield from console.receive(16)))

        platform, console = host_with(script, sp.VirtioConsole())
        # The script's start is a few dozen register accesses, and handing
        # the buffer over a few writes more: ten microseconds is far more
        # than they need, and leaves the host waiting. The second run has
        # only the delivery to do.
        platform.run(sp.us(10))

        console.write("eggs")
        platform.run(sp.us(10))

        assert received == [b"eggs"]


class FakeDevice:
    """A virtio device's registers, with nothing behind them.

    It offers `offered` as its features, and keeps FEATURES_OK unless told
    not to. Reads of anything else give what was last written there, or
    the magic and the version.
    """

    def __init__(
        self,
        *,
        magic=regs.MAGIC_VALUE_AT_RESET,
        offered=0,
        keeps_features_ok=True,
    ):
        self.offered = offered | VERSION_1
        self.keeps_features_ok = keeps_features_ok
        self.registers = {
            regs.MAGIC_VALUE: magic,
            regs.VERSION: regs.VERSION_AT_RESET,
        }

    def __call__(self, operation):
        match operation.kind, operation.operands:
            case "read32", (regs.DEVICE_FEATURES,):
                half = self.registers.get(regs.DEVICE_FEATURES_SEL, 0)
                return (self.offered >> (32 * half)) & 0xFFFF_FFFF
            case "read32", (address,):
                return self.registers.get(address, 0)
            case "write32", (regs.STATUS, value):
                if not self.keeps_features_ok:
                    value &= ~regs.STATUS_FEATURES_OK
                self.registers[regs.STATUS] = value
            case "write32", (address, value):
                self.registers[address] = value
            case _:
                raise AssertionError(f"unexpected {operation}")
        return None


class TestWhenTheDeviceIsNotAVirtioDevice:
    def test_starting_is_refused_and_the_error_names_the_magic(self):
        device = FakeDevice(magic=0x1234_5678)
        host = sp.VirtioHost(registers=0, memory=0x1000)

        with pytest.raises(sp.VirtioError, match="0x12345678"):
            play(host.probe(), device)


class TestWhenTheHostWantsMoreFeaturesThanTheDeviceOffers:
    def test_it_accepts_only_what_was_offered_and_the_modern_layout(self):
        device = FakeDevice(offered=0b10_0010)
        host = sp.VirtioHost(registers=0, memory=0x1000)

        accepted = play(host.negotiate(0b11_1111), device)

        assert accepted == 0b10_0010 | VERSION_1


class TestWhenTheDeviceDoesNotKeepFeaturesOk:
    def test_negotiating_is_refused_and_the_error_says_so(self):
        device = FakeDevice(keeps_features_ok=False)
        host = sp.VirtioHost(registers=0, memory=0x1000)

        with pytest.raises(sp.VirtioError, match="FEATURES_OK"):
            play(host.negotiate(0), device)
