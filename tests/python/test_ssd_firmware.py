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
from socpuppet.boards.drive import VECTORS
from socpuppet.boards.ssd import (
    UPLINK_REACH,
    add_ssd_function,
    stand_in_firmware,
)

RAM_BASE = 0x8000_0000
RAM_SIZE = 0x10_0000
NVME_BASE = 0x1000_0000
# One NAND block of 64 pages of 4 KiB.
BLOCKS = 512
# How many I/O queue pairs the SSD's frontend has, which its firmware
# reads from it (docs/models/nvme-frontend.md).
IO_QUEUE_PAIRS = 8
# Where a raw host puts a command's data: after its four pages of queues.
DATA = RAM_BASE + 0x8000
# An address in the host's map where nothing answers.
NOWHERE = RAM_BASE + RAM_SIZE

# Statuses from the list every command shares, as (type, code).
INVALID_OPCODE = (0, 0x01)
INVALID_FIELD = (0, 0x02)
DATA_TRANSFER_ERROR = (0, 0x04)
INVALID_NAMESPACE = (0, 0x0B)
PRP_OFFSET_INVALID = (0, 0x13)
# And from the list of the commands that create a queue.
COMPLETION_QUEUE_INVALID = (1, 0x00)
INVALID_QUEUE_IDENTIFIER = (1, 0x01)
INVALID_QUEUE_SIZE = (1, 0x02)
INVALID_INTERRUPT_VECTOR = (1, 0x08)


def host_with_an_ssd(script, *, firmware, blocks=BLOCKS):
    """A scripted host with a RAM and an SSD of `blocks` blocks, built.

    `firmware` is the stand-in for the SSD's firmware, or None for an SSD
    with a CPU, into which firmware is still to be loaded. Returns the
    platform and the SSD.
    """
    platform = sp.Platform()
    host = platform.add("host", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=RAM_SIZE))
    ssd = add_ssd_function(
        platform,
        blocks=blocks,
        group=platform.group("ssd"),
        firmware=None if firmware is None else firmware.script,
    )
    platform.connect(host.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(ssd.frontend.bar0, base=NVME_BASE)
    ssd.uplink.map(bus.add_input(), base=0, size=UPLINK_REACH)
    platform.connect(ssd.frontend.irq0, host.irq)
    platform.build()
    return platform, ssd


@pytest.fixture(params=["a script for firmware", "Zephyr for firmware"])
def run_on_an_ssd(request, firmware):
    """Runs a host's script to its end, on a host with an SSD.

    Every test that asks for this runs twice: once with 🎭 the Python
    stand-in for the SSD's firmware, and once with the real thing, the
    Zephyr application in firmware/ssd on the SSD's own CPU. What a host
    sees has to be the same.
    """
    image = (
        firmware("ssd_socpuppet_ssd.elf")
        if request.param == "Zephyr for firmware"
        else None
    )

    def run(script, blocks=BLOCKS):
        finished = []

        def to_its_end():
            yield from script()
            finished.append(True)

        platform, ssd = host_with_an_ssd(
            to_its_end,
            firmware=None if image else stand_in_firmware(),
            blocks=blocks,
        )
        if image:
            platform.load_elf(image, via=ssd.cpu.socket)
        # A script takes no simulated time at all, and the firmware a few
        # milliseconds to boot and less for a command. A second is far
        # more than either, and still ends a run that would never finish.
        platform.run_until(lambda: bool(finished), timeout=sp.ms(1000))
        assert finished, "The host's script did not get to its end."

    return run


def some_data(blocks):
    """Bytes for `blocks` blocks: no two neighbours the same."""
    return bytes(
        (index * 7 + index // 512) % 251 for index in range(blocks * 512)
    )


@pytest.fixture
def what_a_driver_does(run_on_an_ssd):
    """Runs `steps(nvme)` as the host, with the driver stand-in enabled.

    Returns what the steps return.
    """

    def run(steps):
        returned = []

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            returned.append((yield from steps(nvme)))

        run_on_an_ssd(script)
        (value,) = returned
        return value

    return run


@pytest.fixture
def what_a_raw_host_gets(run_on_an_ssd):
    """Runs `steps(host)` as the host, enabled. Returns what they return."""

    def run(steps):
        returned = []

        def script():
            host = RawNvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from host.enable()
            returned.append((yield from steps(host)))

        run_on_an_ssd(script)
        (value,) = returned
        return value

    return run


@pytest.mark.platform
class TestWhenADriverIdentifiesTheSsdsNamespace:
    def test_it_learns_how_many_blocks_the_nand_holds(self, what_a_driver_does):
        def steps(nvme):
            return (yield from nvme.identify_namespace())

        assert what_a_driver_does(steps) == sp.NvmeNamespace(
            blocks=BLOCKS, block_size=512
        )


@pytest.mark.platform
class TestWhenADriverReadsABlockThatWasNeverWritten:
    # An erased NAND page is all ones. The zeros are the firmware's.
    def test_it_gets_a_block_of_zeros(self, what_a_driver_does):
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
    def test_they_are_as_they_were_written(
        self, what_a_driver_does, first, count
    ):
        written = some_data(count)

        def steps(nvme):
            yield from nvme.write_blocks(first=first, data=written)
            return (yield from nvme.read_blocks(first=first, count=count))

        assert what_a_driver_does(steps) == written

    def test_the_blocks_around_them_in_the_same_nand_page_are_untouched(
        self, what_a_driver_does
    ):
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
    def test_they_are_still_there_after_blocks_far_away_are_written(
        self, what_a_driver_does
    ):
        written = some_data(1)

        def steps(nvme):
            yield from nvme.write_blocks(first=0, data=written)
            yield from nvme.write_blocks(
                first=BLOCKS - 1, data=bytes([0x5A]) * 512
            )
            return (yield from nvme.read_blocks(first=0, count=1))

        assert what_a_driver_does(steps) == written

    def test_they_are_still_there_after_a_controller_reset(
        self, what_a_driver_does
    ):
        written = some_data(1)

        def steps(nvme):
            yield from nvme.write_blocks(first=5, data=written)
            # Enabling starts with a reset.
            yield from nvme.enable()
            return (yield from nvme.read_blocks(first=5, count=1))

        assert what_a_driver_does(steps) == written


@pytest.mark.platform
class TestWhenADriverAsksForBlocksPastTheEndOfTheSsd:
    def test_a_read_is_refused_as_out_of_range(self, what_a_driver_does):
        def steps(nvme):
            yield from nvme.read_blocks(first=BLOCKS - 1, count=2)

        with pytest.raises(sp.NvmeError, match=r"(?i)out of range"):
            what_a_driver_does(steps)

    def test_a_write_is_refused_and_writes_nothing(self, what_a_driver_does):
        def steps(nvme):
            with pytest.raises(sp.NvmeError, match=r"(?i)out of range"):
                yield from nvme.write_blocks(
                    first=BLOCKS - 1, data=bytes([0x33]) * 1024
                )
            return (yield from nvme.read_blocks(first=BLOCKS - 1, count=1))

        assert what_a_driver_does(steps) == bytes(512)


@pytest.mark.platform
class TestWhenAHostSendsAnAdminCommandTheSsdDoesNotHave:
    # Opcode 0x7F is one the specification does not assign.
    def test_it_completes_as_an_invalid_opcode(self, what_a_raw_host_gets):
        def steps(host):
            return (yield from host.admin(opcode=0x7F))

        assert what_a_raw_host_gets(steps).status == INVALID_OPCODE


@pytest.mark.platform
class TestWhenAHostIdentifies:
    def identified(self, what_a_raw_host_gets, what, namespace=0):
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

    def test_the_controller_says_it_has_one_namespace(
        self, what_a_raw_host_gets
    ):
        completion, page = self.identified(what_a_raw_host_gets, what=0x01)

        assert completion.status == SUCCESS
        # The number of namespaces is 32 bits at offset 516.
        assert struct.unpack_from("<I", page, 516) == (1,)

    def test_the_list_of_active_namespaces_holds_namespace_one_alone(
        self, what_a_raw_host_gets
    ):
        completion, page = self.identified(what_a_raw_host_gets, what=0x02)

        assert completion.status == SUCCESS
        assert struct.unpack_from("<II", page) == (1, 0)

    def test_namespace_two_is_an_invalid_namespace(self, what_a_raw_host_gets):
        completion, _ = self.identified(
            what_a_raw_host_gets, what=0x00, namespace=2
        )

        assert completion.status == INVALID_NAMESPACE

    # 0x7F is not something Identify can be asked for.
    def test_something_identify_cannot_be_asked_for_is_an_invalid_field(
        self, what_a_raw_host_gets
    ):
        completion, _ = self.identified(what_a_raw_host_gets, what=0x7F)

        assert completion.status == INVALID_FIELD


@pytest.mark.platform
class TestWhenAHostSetsAFeature:
    # Feature 7 is the number of queues. The host asks for one of each, and
    # the answer is what the drive has, counted from zero, in both halves.
    def test_the_number_of_queues_is_answered_with_how_many_the_ssd_has(
        self, what_a_raw_host_gets
    ):
        def steps(host):
            return (
                yield from host.admin(opcode=raw_nvme.SET_FEATURES, dword10=7)
            )

        completion = what_a_raw_host_gets(steps)

        assert completion.status == SUCCESS
        from_zero = IO_QUEUE_PAIRS - 1
        assert completion.result == from_zero << 16 | from_zero

    def test_a_feature_the_ssd_does_not_have_is_an_invalid_field(
        self, what_a_raw_host_gets
    ):
        def steps(host):
            return (
                yield from host.admin(
                    opcode=raw_nvme.SET_FEATURES, dword10=0x7F
                )
            )

        assert what_a_raw_host_gets(steps).status == INVALID_FIELD


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
            pytest.param(
                0,
                8,
                0,
                INVALID_QUEUE_IDENTIFIER,
                id="queue 0 is an invalid queue identifier",
            ),
            pytest.param(
                IO_QUEUE_PAIRS + 1,
                8,
                0,
                INVALID_QUEUE_IDENTIFIER,
                id="one more than the SSD has is an invalid queue identifier",
            ),
            pytest.param(
                2,
                1,
                0,
                INVALID_QUEUE_SIZE,
                id="one entry is an invalid queue size",
            ),
            pytest.param(
                2,
                8,
                VECTORS,
                INVALID_INTERRUPT_VECTOR,
                id="a vector the SSD lacks is an invalid interrupt vector",
            ),
        ],
    )
    def test_it_is_refused(
        self, what_a_raw_host_gets, queue_id, entries, vector, status
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

        assert what_a_raw_host_gets(steps).status == status

    def test_one_that_exists_is_an_invalid_queue_identifier(
        self, what_a_raw_host_gets
    ):
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

        assert what_a_raw_host_gets(steps).status == INVALID_QUEUE_IDENTIFIER


@pytest.mark.platform
class TestWhenAHostAsksForASubmissionQueueItCannotHave:
    @pytest.mark.parametrize(
        ("queue_id", "entries", "status"),
        [
            pytest.param(
                0,
                8,
                INVALID_QUEUE_IDENTIFIER,
                id="queue 0 is an invalid queue identifier",
            ),
            pytest.param(
                IO_QUEUE_PAIRS + 1,
                8,
                INVALID_QUEUE_IDENTIFIER,
                id="one more than the SSD has is an invalid queue identifier",
            ),
            pytest.param(
                1,
                8,
                INVALID_QUEUE_IDENTIFIER,
                id="one that exists is an invalid queue identifier",
            ),
            pytest.param(
                2,
                1,
                INVALID_QUEUE_SIZE,
                id="one entry is an invalid queue size",
            ),
        ],
    )
    def test_it_is_refused(
        self, what_a_raw_host_gets, queue_id, entries, status
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

        assert what_a_raw_host_gets(steps).status == status

    def test_one_before_its_completion_queue_is_a_completion_queue_invalid(
        self, what_a_raw_host_gets
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

        assert what_a_raw_host_gets(steps).status == COMPLETION_QUEUE_INVALID


@pytest.mark.platform
class TestWhenAHostResetsTheSsd:
    # A queue that exists cannot be asked for again, so being given it
    # again says it was gone.
    def test_an_io_queue_it_had_can_be_asked_for_again(
        self, what_a_raw_host_gets
    ):
        def steps(host):
            yield from host.create_io_queues()
            yield from host.disable()
            yield from host.enable()
            return (
                yield from create(
                    host,
                    raw_nvme.CREATE_IO_COMPLETION_QUEUE,
                    queue_id=1,
                    link=0,
                )
            )

        assert what_a_raw_host_gets(steps).status == SUCCESS


@pytest.mark.platform
class TestWhenAHostSendsAnIoCommand:
    def io(self, what_a_raw_host_gets, **command):
        def steps(host):
            yield from host.create_io_queues()
            return (yield from host.io(**command))

        return what_a_raw_host_gets(steps).status

    def test_a_flush_succeeds(self, what_a_raw_host_gets):
        assert (
            self.io(what_a_raw_host_gets, opcode=raw_nvme.FLUSH, namespace=1)
            == SUCCESS
        )

    # Opcode 3 is one the NVM command set does not assign.
    def test_one_the_ssd_does_not_have_is_an_invalid_opcode(
        self, what_a_raw_host_gets
    ):
        assert (
            self.io(what_a_raw_host_gets, opcode=0x03, namespace=1)
            == INVALID_OPCODE
        )

    @pytest.mark.parametrize("opcode", [raw_nvme.READ, raw_nvme.WRITE])
    def test_a_read_or_a_write_of_namespace_two_is_an_invalid_namespace(
        self, what_a_raw_host_gets, opcode
    ):
        assert (
            self.io(what_a_raw_host_gets, opcode=opcode, namespace=2, data=DATA)
            == INVALID_NAMESPACE
        )

    @pytest.mark.parametrize("opcode", [raw_nvme.READ, raw_nvme.WRITE])
    def test_data_where_nothing_answers_is_a_data_transfer_error(
        self, what_a_raw_host_gets, opcode
    ):
        assert (
            self.io(
                what_a_raw_host_gets, opcode=opcode, namespace=1, data=NOWHERE
            )
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

        platform, _ = host_with_an_ssd(script, firmware=firmware)
        platform.run()

        assert firmware.page_map == {63: 0, 0: 1}


@pytest.mark.platform
class TestWhenADriverWritesMorePagesThanOneNandBlockHolds:
    # A NAND block is 64 pages, and the firmware fills the NAND a page at a
    # time, so the 65th page written is the first of the second block. 65
    # pages are 520 of the drive's blocks.
    def test_what_went_to_the_second_nand_block_is_as_it_was_written(
        self, run_on_an_ssd
    ):
        written = some_data(520)
        read_back = []

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=0, data=written)
            read_back.append((yield from nvme.read_blocks(first=0, count=8)))
            read_back.append((yield from nvme.read_blocks(first=512, count=8)))

        run_on_an_ssd(script, blocks=2 * BLOCKS)

        assert read_back == [written[:4096], written[512 * 512 :]]


def page_of(fill):
    """A page of the host's memory, every byte of it `fill`."""
    return bytes([fill]) * 4096


@pytest.mark.platform
class TestWhenACommandsDataIsGivenAsAListOfPages:
    # 🎓 When a command's data is more than two pages, its second pointer
    # is to a list of pointers to the rest. A list that fills its own page
    # ends with a pointer to more of the list.

    def test_a_list_that_runs_on_into_a_second_list_is_followed(
        self, what_a_raw_host_gets
    ):
        # Four pages of data. The list starts 16 bytes before the end of
        # its page, so it has room for two entries: one page of data, and
        # the way on to the second list, which has the other two.
        first_list = DATA + 0x1FF0
        second_list = DATA + 0x2000
        pages = [DATA + 0x3000, DATA + 0x5000, DATA + 0x4000, DATA + 0x6000]

        def steps(host):
            yield from host.create_io_queues()
            for index, page in enumerate(pages):
                yield sp.write(page, page_of(0x10 + index))
            yield sp.write(
                first_list, struct.pack("<QQ", pages[1], second_list)
            )
            yield sp.write(second_list, struct.pack("<QQ", pages[2], pages[3]))
            written = yield from host.io(
                opcode=raw_nvme.WRITE,
                namespace=1,
                data=pages[0],
                more_data=first_list,
                dword12=32 - 1,
            )
            # Read back a page at a time, each into the same place.
            read_back = []
            for index in range(4):
                yield from host.io(
                    opcode=raw_nvme.READ,
                    namespace=1,
                    data=DATA,
                    dword10=8 * index,
                    dword12=8 - 1,
                )
                read_back.append((yield sp.read(DATA, 4096)))
            return written, read_back

        written, read_back = what_a_raw_host_gets(steps)

        assert written.status == SUCCESS
        assert read_back == [page_of(0x10 + index) for index in range(4)]

    def test_a_list_where_nothing_answers_is_a_data_transfer_error(
        self, what_a_raw_host_gets
    ):
        def steps(host):
            yield from host.create_io_queues()
            return (
                yield from host.io(
                    opcode=raw_nvme.WRITE,
                    namespace=1,
                    data=DATA,
                    more_data=NOWHERE,
                    dword12=24 - 1,
                )
            )

        assert what_a_raw_host_gets(steps).status == DATA_TRANSFER_ERROR

    # A pointer is eight bytes, and a list of them starts where one can.
    def test_a_list_that_does_not_start_at_a_pointer_is_a_prp_offset_invalid(
        self, what_a_raw_host_gets
    ):
        def steps(host):
            yield from host.create_io_queues()
            return (
                yield from host.io(
                    opcode=raw_nvme.WRITE,
                    namespace=1,
                    data=DATA,
                    more_data=DATA + 0x2004,
                    dword12=24 - 1,
                )
            )

        assert what_a_raw_host_gets(steps).status == PRP_OFFSET_INVALID


@pytest.mark.platform
class TestWhenAHostIdentifiesWithItsDataWhereNothingAnswers:
    def test_it_is_a_data_transfer_error(self, what_a_raw_host_gets):
        def steps(host):
            return (
                yield from host.admin(
                    opcode=raw_nvme.IDENTIFY, data=NOWHERE, dword10=0x01
                )
            )

        assert what_a_raw_host_gets(steps).status == DATA_TRANSFER_ERROR


def firmware_with_a_flash_controller_whose_status_is(status):
    """The firmware stand-in alone on a bus, with a memory where the flash
    controller's registers would be, whose status register reads `status`.
    Built."""
    flash = 0x3000
    firmware = sp.SsdFirmware(
        frontend=0x1000, dma=0x2000, flash=flash, buffer=0x4000
    )
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(firmware.script))
    bus = platform.add("bus", sp.Router())
    registers = platform.add("flash", sp.Memory(size=0x30))
    platform.connect(cpu.socket, bus.target)
    bus.map(registers.socket, base=flash)
    platform.build()
    platform.poke32(flash + 0x04, status)
    return platform


@pytest.mark.platform
class TestWhenTheFlashControllerNeverFinishes:
    # Bit 2 of its status is BUSY.
    def test_the_firmware_gives_up_and_says_which_device(self):
        platform = firmware_with_a_flash_controller_whose_status_is(1 << 2)

        with pytest.raises(RuntimeError, match="0x3000 is still busy"):
            platform.run()


@pytest.mark.platform
class TestWhenTheFlashControllerCannotIdentifyTheNand:
    # Bit 1 of its status is ERROR. With no geometry there is no drive.
    def test_the_firmware_stops_and_says_so(self):
        platform = firmware_with_a_flash_controller_whose_status_is(1 << 1)

        with pytest.raises(RuntimeError, match="identify the NAND"):
            platform.run()
