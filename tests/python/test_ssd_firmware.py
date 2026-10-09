"""The Python stand-in for an SSD's firmware, on the SSD's hardware.

There is no PCIe here: the drive's registers are mapped straight onto the
host's bus, and its first interrupt line goes straight to the host. What
is behind the registers is the whole SSD.

    host ─▶ bus ─┬─▶ ram
     ▲      ▲    └─▶ ssd.frontend.bar0 ...
     │      └──────── ssd.uplink
     └─────────────── ssd.frontend.irq0
"""

import struct

import pytest

import raw_nvme
import socpuppet as sp
from raw_nvme import SUCCESS, RawNvmeHost
from socpuppet.boards.ssd import add_ssd_function, stand_in_firmware

RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
NVME_BASE = 0x1000_0000
# One NAND block of 64 pages of 4 KiB.
BLOCKS = 512
# Where a raw host puts a command's data: after its four pages of queues.
DATA = RAM_BASE + 0x8000
# An address in the host's map where nothing answers.
NOWHERE = RAM_BASE + RAM_SIZE

# Statuses from the list every command shares, as (type, code).
INVALID_OPCODE = (0, 0x01)
INVALID_FIELD = (0, 0x02)
DATA_TRANSFER_ERROR = (0, 0x04)
INVALID_NAMESPACE = (0, 0x0B)
# And from the list of the commands that create a queue.
COMPLETION_QUEUE_INVALID = (1, 0x00)
INVALID_QUEUE_IDENTIFIER = (1, 0x01)
INVALID_QUEUE_SIZE = (1, 0x02)
INVALID_INTERRUPT_VECTOR = (1, 0x08)


def host_with_an_ssd(script, firmware=None):
    """A scripted host with a RAM and an SSD of BLOCKS blocks, built.

    The SSD's firmware is `firmware`, or a stand-in of the platform's own.
    """
    firmware = firmware or stand_in_firmware()
    platform = sp.Platform()
    host = platform.add("host", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=RAM_SIZE))
    ssd = add_ssd_function(
        platform,
        blocks=BLOCKS,
        group=platform.group("ssd"),
        firmware=firmware.script,
    )
    platform.connect(host.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(ssd.frontend.bar0, base=NVME_BASE)
    ssd.uplink.map(bus.add_input(), base=0, size=1 << 63)
    platform.connect(ssd.frontend.irq0, host.irq)
    platform.build()
    return platform


def some_data(blocks):
    """Bytes for `blocks` blocks: no two neighbours the same."""
    return bytes(
        (index * 7 + index // 512) % 251 for index in range(blocks * 512)
    )


def what_a_driver_does(steps):
    """Runs `steps(nvme)` as the host, with the driver stand-in enabled.

    Returns what the steps return.
    """
    returned = []

    def script():
        nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
        yield from nvme.enable()
        returned.append((yield from steps(nvme)))

    host_with_an_ssd(script).run()
    (value,) = returned
    return value


def what_a_raw_host_gets(steps):
    """Runs `steps(host)` as the host, enabled. Returns what they return."""
    returned = []

    def script():
        host = RawNvmeHost(registers=NVME_BASE, memory=RAM_BASE)
        yield from host.enable()
        returned.append((yield from steps(host)))

    host_with_an_ssd(script).run()
    (value,) = returned
    return value


@pytest.mark.platform
class TestWhenADriverIdentifiesTheSsdsNamespace:
    def test_it_learns_how_many_blocks_the_nand_holds(self):
        def steps(nvme):
            return (yield from nvme.identify_namespace())

        assert what_a_driver_does(steps) == sp.NvmeNamespace(
            blocks=BLOCKS, block_size=512
        )


@pytest.mark.platform
class TestWhenADriverReadsABlockThatWasNeverWritten:
    # An erased NAND page is all ones. The zeros are the firmware's.
    def test_it_gets_a_block_of_zeros(self):
        def steps(nvme):
            return (yield from nvme.read_blocks(first=3, count=1))

        assert what_a_driver_does(steps) == bytes(512)


@pytest.mark.platform
class TestWhenADriverWritesBlocksAndReadsThemBack:
    @pytest.mark.parametrize(
        ("first", "count"),
        [
            pytest.param(3, 1, id="one block, inside a NAND page"),
            pytest.param(8, 16, id="two pages of memory, two NAND pages"),
            pytest.param(13, 24, id="a list of pages, across NAND pages"),
        ],
    )
    def test_they_are_as_they_were_written(self, first, count):
        written = some_data(count)

        def steps(nvme):
            yield from nvme.write_blocks(first=first, data=written)
            return (yield from nvme.read_blocks(first=first, count=count))

        assert what_a_driver_does(steps) == written

    def test_the_blocks_around_them_in_the_same_nand_page_are_untouched(self):
        def steps(nvme):
            yield from nvme.write_blocks(first=2, data=bytes([0x11]) * 512)
            yield from nvme.write_blocks(first=3, data=bytes([0x22]) * 512)
            return (yield from nvme.read_blocks(first=1, count=4))

        assert what_a_driver_does(steps) == (
            bytes(512) + bytes([0x11]) * 512 + bytes([0x22]) * 512 + bytes(512)
        )

    # The firmware has one page of buffer. A drive that only remembered
    # what went through it last would pass a test that reads back what it
    # has just written.
    def test_they_are_still_there_after_blocks_far_away_are_written(self):
        written = some_data(1)

        def steps(nvme):
            yield from nvme.write_blocks(first=0, data=written)
            yield from nvme.write_blocks(
                first=BLOCKS - 1, data=bytes([0x5A]) * 512
            )
            return (yield from nvme.read_blocks(first=0, count=1))

        assert what_a_driver_does(steps) == written

    def test_they_are_still_there_after_a_controller_reset(self):
        written = some_data(1)

        def steps(nvme):
            yield from nvme.write_blocks(first=5, data=written)
            # Enabling starts with a reset.
            yield from nvme.enable()
            return (yield from nvme.read_blocks(first=5, count=1))

        assert what_a_driver_does(steps) == written


@pytest.mark.platform
class TestWhenADriverAsksForBlocksPastTheEndOfTheSsd:
    def test_a_read_is_refused_as_out_of_range(self):
        def steps(nvme):
            yield from nvme.read_blocks(first=BLOCKS - 1, count=2)

        with pytest.raises(sp.NvmeError, match=r"(?i)out of range"):
            what_a_driver_does(steps)

    def test_a_write_is_refused_and_writes_nothing(self):
        def steps(nvme):
            try:
                yield from nvme.write_blocks(
                    first=BLOCKS - 1, data=bytes([0x33]) * 1024
                )
            except sp.NvmeError as refused:
                last = yield from nvme.read_blocks(first=BLOCKS - 1, count=1)
                return str(refused), last
            return None

        why, last_block = what_a_driver_does(steps)
        assert "out of range" in why.lower()
        assert last_block == bytes(512)


@pytest.mark.platform
class TestWhenAHostSendsAnAdminCommandTheSsdDoesNotHave:
    # Opcode 0x7F is one the specification does not assign.
    def test_it_completes_as_an_invalid_opcode(self):
        def steps(host):
            return (yield from host.admin(opcode=0x7F))

        assert what_a_raw_host_gets(steps)[:2] == INVALID_OPCODE


@pytest.mark.platform
class TestWhenAHostIdentifies:
    def identified(self, what, namespace=0):
        """The completion of an Identify, and the page it filled."""

        def steps(host):
            completion = yield from host.admin(
                opcode=raw_nvme.IDENTIFY,
                namespace=namespace,
                data=DATA,
                dword10=what,
            )
            return completion, (yield sp.read(DATA, 4096))

        return what_a_raw_host_gets(steps)

    def test_the_controller_says_it_has_one_namespace(self):
        completion, page = self.identified(what=0x01)

        assert completion[:2] == SUCCESS
        # The number of namespaces is 32 bits at offset 516.
        assert struct.unpack_from("<I", page, 516) == (1,)

    def test_the_list_of_active_namespaces_holds_namespace_one_alone(self):
        completion, page = self.identified(what=0x02)

        assert completion[:2] == SUCCESS
        assert struct.unpack_from("<II", page) == (1, 0)

    def test_namespace_two_is_an_invalid_namespace(self):
        completion, _ = self.identified(what=0x00, namespace=2)

        assert completion[:2] == INVALID_NAMESPACE

    # 0x7F is not something Identify can be asked for.
    def test_something_there_is_not_is_an_invalid_field(self):
        completion, _ = self.identified(what=0x7F)

        assert completion[:2] == INVALID_FIELD


@pytest.mark.platform
class TestWhenAHostSetsAFeature:
    # Feature 7 is the number of queues. The host asks for one of each, and
    # the answer is what the drive has, counted from zero, in both halves.
    def test_the_number_of_queues_is_answered_with_how_many_the_ssd_has(self):
        def steps(host):
            return (
                yield from host.admin(opcode=raw_nvme.SET_FEATURES, dword10=7)
            )

        completion = what_a_raw_host_gets(steps)

        assert completion[:2] == SUCCESS
        assert completion.result == 7 << 16 | 7

    def test_a_feature_the_ssd_does_not_have_is_an_invalid_field(self):
        def steps(host):
            return (
                yield from host.admin(
                    opcode=raw_nvme.SET_FEATURES, dword10=0x7F
                )
            )

        assert what_a_raw_host_gets(steps)[:2] == INVALID_FIELD


def create(host, opcode, *, queue_id, entries=8, link):
    """Asks for a queue of `entries` entries. `link` is a completion queue's
    interrupt vector, or the completion queue of a submission queue."""
    return host.admin(
        opcode=opcode,
        data=DATA,
        dword10=(entries - 1) << 16 | queue_id,
        dword11=link << 16,
    )


@pytest.mark.platform
class TestWhenAHostAsksForACompletionQueueItCannotHave:
    @pytest.mark.parametrize(
        ("queue_id", "entries", "vector", "status"),
        [
            pytest.param(0, 8, 0, INVALID_QUEUE_IDENTIFIER, id="queue 0"),
            pytest.param(9, 8, 0, INVALID_QUEUE_IDENTIFIER, id="a ninth"),
            pytest.param(2, 1, 0, INVALID_QUEUE_SIZE, id="of one entry"),
            pytest.param(2, 8, 2, INVALID_INTERRUPT_VECTOR, id="on vector 2"),
        ],
    )
    def test_the_command_fails_with_the_status_for_it(
        self, queue_id, entries, vector, status
    ):
        def steps(host):
            return (
                yield from create(
                    host,
                    raw_nvme.CREATE_IO_COMPLETION_QUEUE,
                    queue_id=queue_id,
                    entries=entries,
                    link=vector,
                )
            )

        assert what_a_raw_host_gets(steps)[:2] == status

    def test_one_that_exists_is_an_invalid_queue_identifier(self):
        def steps(host):
            yield from host.create_io_queues()
            return (
                yield from create(
                    host,
                    raw_nvme.CREATE_IO_COMPLETION_QUEUE,
                    queue_id=1,
                    link=0,
                )
            )

        assert what_a_raw_host_gets(steps)[:2] == INVALID_QUEUE_IDENTIFIER


@pytest.mark.platform
class TestWhenAHostAsksForASubmissionQueueItCannotHave:
    @pytest.mark.parametrize(
        ("queue_id", "entries", "status"),
        [
            pytest.param(0, 8, INVALID_QUEUE_IDENTIFIER, id="queue 0"),
            pytest.param(9, 8, INVALID_QUEUE_IDENTIFIER, id="a ninth"),
            pytest.param(1, 8, INVALID_QUEUE_IDENTIFIER, id="one that exists"),
            pytest.param(2, 1, INVALID_QUEUE_SIZE, id="of one entry"),
        ],
    )
    def test_the_command_fails_with_the_status_for_it(
        self, queue_id, entries, status
    ):
        def steps(host):
            yield from host.create_io_queues()
            return (
                yield from create(
                    host,
                    raw_nvme.CREATE_IO_SUBMISSION_QUEUE,
                    queue_id=queue_id,
                    entries=entries,
                    link=1,
                )
            )

        assert what_a_raw_host_gets(steps)[:2] == status

    def test_one_before_its_completion_queue_is_a_completion_queue_invalid(
        self,
    ):
        def steps(host):
            return (
                yield from create(
                    host,
                    raw_nvme.CREATE_IO_SUBMISSION_QUEUE,
                    queue_id=1,
                    link=1,
                )
            )

        assert what_a_raw_host_gets(steps)[:2] == COMPLETION_QUEUE_INVALID


@pytest.mark.platform
class TestWhenAHostResetsTheSsd:
    def test_the_io_queues_are_gone_and_can_be_asked_for_again(self):
        def steps(host):
            yield from host.create_io_queues()
            yield from host.disable()
            yield from host.enable()
            # This asserts that both queues were created.
            yield from host.create_io_queues()
            return (yield from host.io(opcode=raw_nvme.FLUSH, namespace=1))

        assert what_a_raw_host_gets(steps)[:2] == SUCCESS


@pytest.mark.platform
class TestWhenAHostSendsAnIoCommand:
    def io(self, **command):
        def steps(host):
            yield from host.create_io_queues()
            return (yield from host.io(**command))

        return what_a_raw_host_gets(steps)[:2]

    def test_a_flush_succeeds(self):
        assert self.io(opcode=raw_nvme.FLUSH, namespace=1) == SUCCESS

    # Opcode 3 is one the NVM command set does not assign.
    def test_one_the_ssd_does_not_have_is_an_invalid_opcode(self):
        assert self.io(opcode=0x03, namespace=1) == INVALID_OPCODE

    @pytest.mark.parametrize("opcode", [raw_nvme.READ, raw_nvme.WRITE])
    def test_a_read_or_a_write_of_namespace_two_is_an_invalid_namespace(
        self, opcode
    ):
        assert (
            self.io(opcode=opcode, namespace=2, data=DATA) == INVALID_NAMESPACE
        )

    @pytest.mark.parametrize("opcode", [raw_nvme.READ, raw_nvme.WRITE])
    def test_data_where_nothing_answers_is_a_data_transfer_error(self, opcode):
        assert (
            self.io(opcode=opcode, namespace=1, data=NOWHERE)
            == DATA_TRANSFER_ERROR
        )


@pytest.mark.platform
class TestWhenADriverHasWrittenToPagesOfTheSsd:
    # A NAND page is eight of the drive's blocks, so block 504 is in page
    # 63 of the drive and block 0 in page 0. The firmware gives each the
    # next NAND page nobody has, in the order they were first written.
    def test_the_firmware_can_say_which_nand_page_holds_each(self):
        firmware = stand_in_firmware()

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=504, data=bytes(512))
            yield from nvme.write_blocks(first=0, data=bytes(512))
            yield from nvme.write_blocks(first=505, data=bytes(512))

        host_with_an_ssd(script, firmware).run()

        assert firmware.page_map == {63: 0, 0: 1}
