"""🧵 Python as the first driver of a virtio device.

The platform tests run the driver against the entropy device, the smallest
virtio device there is, the console, the disk, the network device,
the file system device and the 9P transport, on a scripted host; the rest play
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


@pytest.mark.platform
class TestWhenTheHostSendsAFrame:
    def test_python_finds_it_on_the_wire_without_its_header(self):
        def script():
            net = sp.VirtioNetHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from net.start()
            yield from net.send_frame(b"spam frame")

        platform, net = host_with(script, sp.VirtioNet())

        platform.run()

        assert net.received == [b"spam frame"]


@pytest.mark.platform
class TestWhenPythonAsksForTheFramesSentAfterTheFirstOne:
    def test_it_is_given_only_the_later_ones_in_order(self):
        def script():
            net = sp.VirtioNetHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from net.start()
            yield from net.send_frame(b"spam frame")
            yield from net.send_frame(b"eggs frame")
            yield from net.send_frame(b"spam and eggs frame")

        platform, net = host_with(script, sp.VirtioNet())

        platform.run()

        assert net.received_since(1) == [b"eggs frame", b"spam and eggs frame"]


@pytest.mark.platform
class TestWhenPythonSendsAFrameWhileTheHostWaitsForOne:
    def test_the_host_receives_it(self):
        received = []

        def script():
            net = sp.VirtioNetHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from net.start()
            received.append((yield from net.receive_frame()))

        platform, net = host_with(script, sp.VirtioNet())
        # As for the console: long enough for the start and the buffer.
        platform.run(sp.us(10))

        net.send(b"eggs frame")
        platform.run(sp.us(10))

        assert received == [b"eggs frame"]


@pytest.mark.platform
class TestWhenPythonSendsAFrameLongerThanTheHostsBuffer:
    def test_it_is_dropped_and_counted(self):
        def script():
            net = sp.VirtioNetHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from net.start()
            yield from net.receive_frame()

        platform, net = host_with(script, sp.VirtioNet())
        # As before: long enough for the start and the buffer.
        platform.run(sp.us(10))

        net.send(bytes(sp.VirtioNetHost.FRAME_ROOM + 1))
        platform.run(sp.us(10))

        assert net.dropped == 1


class TestWhenANetworkDeviceIsGivenAnAddressWiderThan48Bits:
    def test_it_is_refused_and_the_error_says_how_wide_one_is(self):
        with pytest.raises(ValueError, match="48 bits"):
            sp.VirtioNet(mac=1 << 48)


@pytest.mark.platform
class TestWhenTheHostReadsAFileFromAShareServedByPython:
    def test_it_gets_what_python_put_in_the_directory(self, tmp_path):
        (tmp_path / "spam.txt").write_bytes(b"spam, spam, spam")
        read = []

        def script():
            fs = sp.VirtioFsHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from fs.start()
            yield from fs.init()
            node = yield from fs.lookup("spam.txt")
            handle = yield from fs.open(node)
            read.append((yield from fs.read(node, handle, size=64)))

        platform, _ = host_with(
            script, sp.VirtioFs(tag="spam", directory=tmp_path)
        )

        platform.run()

        assert read == [b"spam, spam, spam"]


@pytest.mark.platform
class TestWhenTheHostLooksUpANameThatIsNotInTheShare:
    def test_the_error_comes_out_of_the_run_and_names_it(self, tmp_path):
        def script():
            fs = sp.VirtioFsHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from fs.start()
            yield from fs.init()
            yield from fs.lookup("ham.txt")

        platform, _ = host_with(
            script, sp.VirtioFs(tag="spam", directory=tmp_path)
        )

        with pytest.raises(sp.VirtioError, match=r"ham\.txt.*ENOENT"):
            platform.run()


class TestWhenAShareIsGivenATagLongerThanTheDeviceHolds:
    def test_it_is_refused_and_the_error_says_how_long_one_may_be(
        self, tmp_path
    ):
        with pytest.raises(ValueError, match="36 bytes"):
            sp.VirtioFs(tag="s" * 37, directory=tmp_path)


@pytest.mark.platform
class TestWhenTheHostReadsAFileFromA9pShareServedByPython:
    def test_it_gets_what_python_put_in_the_directory(self, tmp_path):
        (tmp_path / "spam.txt").write_bytes(b"spam, spam, spam")
        read = []

        def script():
            ninep = sp.Virtio9pHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from ninep.start()
            yield from ninep.attach()
            fid = yield from ninep.open("spam.txt")
            read.append((yield from ninep.read(fid, size=64)))

        platform, _ = host_with(
            script, sp.Virtio9p(tag="spam", directory=tmp_path)
        )

        platform.run()

        assert read == [b"spam, spam, spam"]


@pytest.mark.platform
class TestWhenTheHostOpensANameThatIsNotInThe9pShare:
    def test_the_error_comes_out_of_the_run_and_names_it(self, tmp_path):
        def script():
            ninep = sp.Virtio9pHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from ninep.start()
            yield from ninep.attach()
            yield from ninep.open("ham.txt")

        platform, _ = host_with(
            script, sp.Virtio9p(tag="spam", directory=tmp_path)
        )

        with pytest.raises(
            sp.VirtioError, match=r"Twalk of 'ham\.txt'.*ENOENT"
        ):
            platform.run()


class TestWhenA9pShareIsGivenATagLongerThanTheConfigurationHolds:
    def test_it_is_refused_and_the_error_says_how_long_one_may_be(
        self, tmp_path
    ):
        # 🎓 The tag follows its two-byte length in the transport's 256
        # bytes of configuration.
        with pytest.raises(ValueError, match="254 bytes"):
            sp.Virtio9p(tag="s" * 255, directory=tmp_path)


SECTOR = 512


@pytest.mark.platform
class TestWhenTheHostWritesTwoSectorsAndReadsThemBack:
    def test_it_reads_what_it_wrote_and_python_finds_it_on_the_disk(self):
        written = b"s" * SECTOR + b"e" * SECTOR
        answers = []

        def script():
            disk = sp.VirtioBlkHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from disk.start()
            yield from disk.write_sectors(first=2, data=written)
            answers.append((yield from disk.read_sectors(first=2, count=2)))

        platform, disk = host_with(script, sp.VirtioBlk(blocks=8))

        platform.run()

        assert answers == [written]
        assert disk.contents[2 * SECTOR : 4 * SECTOR] == written


@pytest.mark.platform
class TestWhenPythonPutsAnImageOnTheDiskBeforeTheRun:
    def test_its_last_sector_is_padded_and_the_rest_left_as_it_was(self):
        answers = []

        def script():
            disk = sp.VirtioBlkHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from disk.start()
            answers.append((yield from disk.read_sectors(first=0, count=2)))

        platform, disk = host_with(script, sp.VirtioBlk(blocks=8))
        disk.load(b"e" * 2 * SECTOR)
        disk.load(b"spam")

        platform.run()

        assert answers == [b"spam" + bytes(SECTOR - 4) + b"e" * SECTOR]


@pytest.mark.platform
class TestWhenTheHostReadsPastTheEndOfTheDisk:
    def test_the_error_comes_out_of_the_run_and_names_the_status(self):
        def script():
            disk = sp.VirtioBlkHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from disk.start()
            # The disk has 8 sectors, numbered from 0.
            yield from disk.read_sectors(first=8, count=1)

        platform, _ = host_with(script, sp.VirtioBlk(blocks=8))

        with pytest.raises(sp.VirtioError, match="IOERR"):
            platform.run()


@pytest.mark.platform
class TestWhenTheHostWritesPastTheEndOfTheDisk:
    def test_the_error_comes_out_of_the_run_and_says_what_to_check(self):
        def script():
            disk = sp.VirtioBlkHost(registers=DEVICE_BASE, memory=RAM_BASE)
            yield from disk.start()
            yield from disk.write_sectors(first=7, data=bytes(2 * SECTOR))

        platform, _ = host_with(script, sp.VirtioBlk(blocks=8))

        with pytest.raises(sp.VirtioError, match=r"IOERR.*past the end"):
            platform.run()


@pytest.mark.platform
class TestWhenPythonPutsAnImageOnTheDiskThatIsLargerThanIt:
    def test_it_is_refused_and_the_error_gives_both_sizes(self):
        def script():
            yield from ()

        _, disk = host_with(script, sp.VirtioBlk(blocks=8))

        with pytest.raises(ValueError, match=r"4097 bytes.*4096"):
            disk.load(bytes(8 * SECTOR + 1))


@pytest.mark.platform
class TestWhenADiskIsDescribedWithNoBlocks:
    def test_building_it_is_refused_and_the_error_gives_the_range(self):
        def script():
            yield from ()

        with pytest.raises(ValueError, match=r'"blocks" from 1 to '):
            host_with(script, sp.VirtioBlk(blocks=0))


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
