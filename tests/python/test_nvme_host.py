"""The Python host driver stand-in.

Most tests run it against the behavioral NVMe, and a few play it against a
fake controller with no simulator at all. There is no PCIe here: the
drive's registers are mapped straight onto the host's bus, and its first
interrupt line goes straight to the host.

    host ─▶ bus ─┬─▶ ram
     ▲      ▲    └─▶ nvme.bar0
     │      └──────── nvme.dma
     └─────────────── nvme.irq0
"""

import pytest

import socpuppet as sp
from scripts import play

RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
NVME_BASE = 0x1000_0000


def host_with_nvme(script, blocks=64):
    """A scripted host with a RAM and a `blocks`-block drive, built."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=RAM_SIZE))
    nvme = platform.add("nvme", sp.BehavioralNvme(blocks=blocks))
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(nvme.bar0, base=NVME_BASE)
    platform.connect(nvme.dma, bus.add_input())
    platform.connect(nvme.irq0, cpu.irq)
    platform.build()
    return platform


@pytest.mark.platform
class TestWhenTheHostIdentifiesNamespaceOne:
    def test_it_learns_how_many_blocks_the_drive_holds(self):
        learned = []

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            learned.append((yield from nvme.identify_namespace()))

        platform = host_with_nvme(script, blocks=64)

        platform.run()

        assert [namespace.blocks for namespace in learned] == [64]


@pytest.mark.platform
class TestWhenTheHostReadsABlockThatWasNeverWritten:
    def test_it_gets_a_block_of_zeros(self):
        blocks = []

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            blocks.append((yield from nvme.read_blocks(first=0, count=1)))

        platform = host_with_nvme(script)
        # Nothing in the host's memory is zero to begin with, so the zeros
        # have to come from the drive.
        platform.poke(RAM_BASE, b"\xa5" * RAM_SIZE)

        platform.run()

        assert blocks == [bytes(512)]


@pytest.mark.platform
class TestWhenTheHostWritesBlocksAndReadsThemBack:
    def test_one_block_comes_back_as_it_was_written(self):
        written = bytes(range(256)) * 2
        read_back = []

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=3, data=written)
            read_back.append((yield from nvme.read_blocks(first=3, count=1)))

        platform = host_with_nvme(script)

        platform.run()

        assert read_back == [written]

    def test_two_pages_of_blocks_come_back_as_they_were_written(self):
        # 16 blocks is two pages of memory, and the command points at both.
        written = bytes(index * 7 % 251 for index in range(16 * 512))
        read_back = []

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=0, data=written)
            read_back.append((yield from nvme.read_blocks(first=0, count=16)))

        platform = host_with_nvme(script)

        platform.run()

        assert read_back == [written]

    def test_three_pages_of_blocks_come_back_as_they_were_written(self):
        # 24 blocks is three pages of memory, which is more than a command
        # can point at without a list of pages.
        written = bytes(index * 7 % 251 for index in range(24 * 512))
        read_back = []

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=0, data=written)
            read_back.append((yield from nvme.read_blocks(first=0, count=24)))

        platform = host_with_nvme(script)

        platform.run()

        assert read_back == [written]


@pytest.mark.platform
class TestWhenTheHostWritesDataThatIsNotWholeBlocks:
    def test_it_is_refused_and_the_error_names_the_length(self):
        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=0, data=bytes(100))

        platform = host_with_nvme(script)

        with pytest.raises(ValueError, match="100 bytes"):
            platform.run()


@pytest.mark.platform
class TestWhenTheControllerFailsACommand:
    def test_the_error_comes_out_of_the_run_and_names_the_status(self):
        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            # The drive has 64 blocks, numbered from 0.
            yield from nvme.read_blocks(first=64, count=1)

        platform = host_with_nvme(script, blocks=64)

        with pytest.raises(sp.NvmeError, match="LBA Out of Range"):
            platform.run()


@pytest.mark.platform
class TestWhenTheHostEnablesTheControllerASecondTime:
    def test_a_block_written_before_still_reads_back(self):
        written = bytes(range(256)) * 2
        read_back = []

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=0, data=written)
            yield from nvme.enable()
            read_back.append((yield from nvme.read_blocks(first=0, count=1)))

        platform = host_with_nvme(script)

        platform.run()

        assert read_back == [written]


@pytest.mark.platform
class TestWhenTheHostSendsMoreCommandsThanItsQueuesHaveEntries:
    def test_the_last_one_still_reads_what_was_written(self):
        # Queues of four entries, so the ninth read has been round both
        # rings twice.
        written = bytes(range(256)) * 2
        read_back = []

        def script():
            nvme = sp.NvmeHost(
                registers=NVME_BASE, memory=RAM_BASE, queue_entries=4
            )
            yield from nvme.enable()
            yield from nvme.write_blocks(first=0, data=written)
            for _ in range(9):
                last = yield from nvme.read_blocks(first=0, count=1)
            read_back.append(last)

        platform = host_with_nvme(script)

        platform.run()

        assert read_back == [written]


class TestWhenTheHostIsGivenMemoryThatDoesNotStartOnAPage:
    def test_it_is_refused_and_the_error_says_why(self):
        with pytest.raises(ValueError, match="page"):
            sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE + 0x10)


class TestWhenTheHostIsGivenQueuesOfALengthItCannotUse:
    # A queue needs two entries to be a ring at all, and its ring is one
    # page of memory, which holds 64 commands.
    @pytest.mark.parametrize("entries", [1, 65])
    def test_it_is_refused_and_the_error_gives_the_range(self, entries):
        with pytest.raises(ValueError, match="2 to 64"):
            sp.NvmeHost(
                registers=NVME_BASE, memory=RAM_BASE, queue_entries=entries
            )


@pytest.mark.platform
class TestWhenTheHostAsksForATransferItCannotDescribeInOneCommand:
    def test_no_blocks_at_all_is_refused_and_the_error_says_so(self):
        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.read_blocks(first=0, count=0)

        platform = host_with_nvme(script)

        with pytest.raises(ValueError, match="at least one block"):
            platform.run()

    def test_more_than_one_list_of_pages_is_refused_and_the_error_gives_the_limit(
        self,
    ):
        # A list of pages is one page long, which is 512 entries. With the
        # page the command itself points at, that is 513 pages of data, or
        # 4104 blocks of 512 bytes.
        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.read_blocks(first=0, count=4105)

        platform = host_with_nvme(script)

        with pytest.raises(ValueError, match="4104 blocks"):
            platform.run()


class TestWhenTheControllerNeverBecomesReady:
    def test_enabling_gives_up_after_the_time_the_controller_allows(self):
        # CAP.TO, in bits 31 to 24 of the capabilities register, counts in
        # units of 500 ms. This controller allows one.
        bus = FakeController(
            capabilities=1 << 24 | MOST_ENTRIES, becomes_ready=False
        )
        nvme = sp.NvmeHost(registers=0, memory=0x1000)

        with pytest.raises(sp.NvmeError, match="500 ms"):
            play(nvme.enable(), bus)

        assert bus.waited == sp.ms(500)


class TestWhenAnInterruptComesWithNoCompletionForTheCommand:
    def test_the_error_says_to_check_what_drives_the_interrupt_line(self):
        bus = FakeController(completes=False)
        nvme = sp.NvmeHost(registers=0, memory=0x1000)

        with pytest.raises(sp.NvmeError, match="irq"):
            play(nvme.enable(), bus)


class TestWhenTheControllerFailsACommandWithAStatusTheDriverCannotName:
    def test_the_error_gives_the_status_as_numbers(self):
        bus = FakeController(status_code=0x7F)
        nvme = sp.NvmeHost(registers=0, memory=0x1000)

        with pytest.raises(sp.NvmeError, match="status code 0x7f"):
            play(nvme.enable(), bus)


class TestWhenTheControllersDoorbellsAreFurtherApartThanFourBytes:
    def test_the_driver_rings_them_where_the_controller_says_they_are(self):
        # CAP.DSTRD, in bits 35 to 32, is the doorbell stride: the
        # doorbells are 4 << DSTRD bytes apart. Here that is 8, so the
        # admin completion queue's doorbell, the second, is at 0x1008.
        bus = FakeController(capabilities=1 << 32 | MOST_ENTRIES)
        nvme = sp.NvmeHost(registers=0, memory=0x1000)

        play(nvme.enable(), bus)

        assert 0x1008 in bus.doorbells_rung
        assert 0x1004 not in bus.doorbells_rung


class TestWhenTheDriversQueuesAreLongerThanTheControllerTakes:
    def test_enabling_is_refused_and_the_error_gives_both_lengths(self):
        # CAP.MQES, in bits 15 to 0, is the longest queue the controller
        # takes, counted from zero: here 8 entries.
        bus = FakeController(capabilities=7)
        nvme = sp.NvmeHost(registers=0, memory=0x1000, queue_entries=16)

        with pytest.raises(sp.NvmeError, match=r"16 entries.*at most 8"):
            play(nvme.enable(), bus)


class TestWhenTheControllerReportsAFatalError:
    def test_enabling_stops_and_the_error_says_so(self):
        bus = FakeController(fatal=True)
        nvme = sp.NvmeHost(registers=0, memory=0x1000)

        with pytest.raises(sp.NvmeError, match="fatal"):
            play(nvme.enable(), bus)


class TestWhenACompletionCarriesNoCommandIdentifier:
    def test_it_is_not_taken_for_the_first_commands(self):
        # A slot that says it is new and whose identifier is zero: what a
        # controller that never filled the identifier in would leave.
        bus = FakeController(identifies_completions=False)
        nvme = sp.NvmeHost(registers=0, memory=0x1000)

        with pytest.raises(sp.NvmeError, match="no completion"):
            play(nvme.enable(), bus)


class TestWhenTheHostIsGivenLessMemoryThanItsQueuesTake:
    def test_it_is_refused_and_the_error_says_how_much_they_take(self):
        with pytest.raises(ValueError, match="4 pages"):
            sp.NvmeHost(
                registers=NVME_BASE, memory=RAM_BASE, memory_size=3 * 4096
            )


@pytest.mark.platform
class TestWhenATransferNeedsMoreMemoryThanTheHostWasGiven:
    def test_the_error_comes_out_of_the_run_and_says_what_was_given(self):
        def script():
            # Four pages for the queues, and one for data.
            nvme = sp.NvmeHost(
                registers=NVME_BASE, memory=RAM_BASE, memory_size=5 * 4096
            )
            yield from nvme.enable()
            # Sixteen blocks are two pages.
            yield from nvme.read_blocks(first=0, count=16)

        platform = host_with_nvme(script)

        with pytest.raises(sp.NvmeError, match="5 pages"):
            platform.run()


# The longest queue a controller can say it takes (CAP.MQES, from zero).
MOST_ENTRIES = 0xFFFF


class FakeController:
    """Just enough of a controller to enable against, with no simulator.

    It is ready when it is enabled, unless told never to be, and every
    other register reads as zero. It completes each command it is sent
    with `status_code`, unless told not to complete any. It adds up how
    long the driver waited, and notes which doorbells were rung.
    """

    def __init__(
        self,
        *,
        capabilities=MOST_ENTRIES,
        becomes_ready=True,
        fatal=False,
        completes=True,
        identifies_completions=True,
        status_code=0,
    ):
        self.capabilities = capabilities
        self.becomes_ready = becomes_ready
        self.fatal = fatal
        self.completes = completes
        self.identifies_completions = identifies_completions
        self.status_code = status_code
        self.enabled = False
        self.waited = 0
        self.last_command = bytes(64)
        self.doorbells_rung = []

    def __call__(self, operation):
        configuration, status = 0x14, 0x1C
        if operation.kind == "write32" and operation.operands[0] >= 0x1000:
            self.doorbells_rung.append(operation.operands[0])
        if (
            operation.kind == "write32"
            and operation.operands[0] == configuration
        ):
            self.enabled = bool(operation.operands[1] & 1)
        if operation.kind == "write" and len(operation.operands[1]) == 64:
            self.last_command = operation.operands[1]
        if operation.kind == "read32":
            # The capabilities register is 64 bits, in two halves.
            if operation.operands[0] == 0x00:
                return self.capabilities & 0xFFFF_FFFF
            if operation.operands[0] == 0x04:
                return self.capabilities >> 32
            if operation.operands[0] == status:
                return int(self.enabled and self.becomes_ready) | (
                    2 if self.fatal else 0
                )
            return 0
        if operation.kind == "read":
            return self._completion()
        if operation.kind == "wait":
            self.waited += operation.operands[0]
        return None

    def _completion(self):
        if not self.completes:
            return bytes(16)
        # A completion carries its command's identifier (bytes 2 and 3 of
        # the command) in bytes 12 and 13. Its last 16 bits are the phase
        # bit, which is 1 the first time round, and above it the status
        # code.
        status = (self.status_code << 1 | 1).to_bytes(2, "little")
        identifier = (
            self.last_command[2:4] if self.identifies_completions else bytes(2)
        )
        return bytes(12) + identifier + status
