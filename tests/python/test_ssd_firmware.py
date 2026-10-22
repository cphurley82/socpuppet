"""An SSD's firmware, on the SSD's hardware, as a host sees it.

There are two firmwares, and a host is not to tell them apart. So every
test here runs twice: once with 🎭 the Python stand-in, `sp.SsdFirmware`,
and once with the real thing, the Zephyr application in firmware/ssd on
the SSD's own CPU. What only one of them does is in
test_ssd_scripted_firmware.py and test_ssd_zephyr_firmware.py.

There is no PCIe here (see ssd_on_a_bus.py).
"""

import struct

import pytest

import raw_nvme
import socpuppet as sp
from raw_nvme import SUCCESS, RawNvmeHost
from socpuppet import ftl
from socpuppet.boards.drive import VECTORS
from socpuppet.boards.ssd import scripted_firmware
from ssd_on_a_bus import (
    BLOCKS,
    NVME_BASE,
    RAM_BASE,
    RAM_SIZE,
    host_with_an_ssd,
)
from ssd_zephyr_firmware import IMAGE as SSD_IMAGE

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


@pytest.fixture(params=["a script for firmware", "Zephyr for firmware"])
def run_on_an_ssd(request, firmware):
    """Runs a host's script to its end, on a host with an SSD.

    Every test that asks for this runs twice: once with 🎭 the Python
    stand-in for the SSD's firmware, and once with the real thing, the
    Zephyr application in firmware/ssd on the SSD's own CPU. What a host
    sees has to be the same, and what the SSD keeps on its NAND. Returns
    the SSD. With a `drive`, the SSD's NAND is programmed with it before
    the run, as a factory does (`socpuppet.ftl.nand_image`); with `nand`,
    a function of the chip, with the image it gives.
    """
    image = (
        firmware(SSD_IMAGE) if request.param == "Zephyr for firmware" else None
    )

    def run(script, blocks=BLOCKS, drive=None, nand=None):
        finished = []

        def to_its_end():
            yield from script()
            finished.append(True)

        platform, ssd = host_with_an_ssd(
            to_its_end,
            firmware=None if image else scripted_firmware(),
            blocks=blocks,
        )
        if image:
            platform.load_elf(image, via=ssd.cpu.socket)
        assert drive is None or nand is None, "One image for the NAND."
        if drive is not None:
            ssd.nand.load(ftl.nand_image(drive, ssd.nand.component))
        if nand is not None:
            ssd.nand.load(nand(ssd.nand.component))
        # A script takes no simulated time at all, and the firmware a few
        # milliseconds to boot and less for a command. A second is far
        # more than either, and still ends a run that would never finish.
        platform.run_until(lambda: bool(finished), timeout=sp.ms(1000))
        assert finished, "The host's script did not get to its end."
        return ssd

    return run


def some_data(blocks):
    """Bytes for `blocks` blocks: no two neighbours the same."""
    return bytes(
        (index * 7 + index // 512) % 251 for index in range(blocks * 512)
    )


@pytest.fixture
def what_a_driver_does(run_on_an_ssd):
    """Runs `steps(nvme)` as the host, with the driver stand-in enabled.

    The SSD has `blocks` blocks, and was programmed with `drive` at the
    factory, if one is given, or with the image `nand` gives for the chip.
    Returns what the steps return.
    """

    def run(steps, blocks=BLOCKS, drive=None, nand=None):
        returned = []

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            returned.append((yield from steps(nvme)))

        run_on_an_ssd(script, blocks=blocks, drive=drive, nand=nand)
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
    def test_it_learns_the_blocks_the_drive_was_described_with(
        self, what_a_driver_does
    ):
        # 🎓 Not the whole NAND: its first blocks are the FTL's reserve.
        def steps(nvme):
            return (yield from nvme.identify_namespace())

        assert what_a_driver_does(steps) == sp.NvmeNamespace(
            blocks=BLOCKS, block_size=512
        )


@pytest.mark.platform
class TestWhenADriverWritesAPageOfTheDrive:
    def test_it_goes_in_the_first_nand_page_after_the_ftls_reserve(
        self, run_on_an_ssd
    ):
        # 🎓 The first page of the drive to be written takes the first NAND
        # page nobody has, wherever it is on the drive: the reserve's pages
        # are the FTL's own.
        written = some_data(8)

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=24, data=written)

        nand = run_on_an_ssd(script).nand

        assert the_first_nand_page_after_the_reserve(nand)[: len(written)] == (
            written
        )


def the_first_nand_page_after_the_reserve(nand):
    """The bytes of the first NAND page the FTL does not keep for itself."""
    chip = nand.component
    shared = ftl.layout(
        chip.blocks,
        pages_per_block=chip.pages_per_block,
        page_size=chip.page_size,
    )
    first = shared.reserve_pages * chip.page_size
    return nand.contents[first : first + chip.page_size]


@pytest.mark.platform
class TestWhenTheSsdsNandWasProgrammedAtTheFactory:
    def test_a_driver_reads_the_drive_it_was_programmed_with(
        self, what_a_driver_does
    ):
        # 🎓 The firmware finds the table the factory put in the reserve,
        # and the drive's pages where it says. A page of zeros is in no
        # NAND page, and reads as zeros all the same.
        data = some_data(32)
        drive = data[: 16 * 512] + bytes(8 * 512) + data[24 * 512 :]

        def steps(nvme):
            return (
                yield from nvme.read_blocks(first=0, count=len(drive) // 512)
            )

        assert what_a_driver_does(steps, drive=drive) == drive


@pytest.mark.platform
class TestWhenTheNandHasThisDrivesHeaderAndATableThatCannotBeIts:
    @pytest.mark.parametrize(
        ("where_page_0", "next_free"),
        [
            pytest.param(
                lambda shared: 0,
                lambda shared: shared.reserve_pages + 1,
                id="an entry in the reserve",
            ),
            pytest.param(
                lambda shared: shared.reserve_pages + 1,
                lambda shared: shared.reserve_pages + 1,
                id="an entry at the next free page, which nobody has yet",
            ),
            pytest.param(
                lambda shared: shared.reserve_pages,
                lambda shared: shared.reserve_pages + shared.drive_pages + 1,
                id="next free past the chip",
            ),
        ],
    )
    def test_a_driver_reads_a_drive_of_zeros(
        self, what_a_driver_does, where_page_0, next_free
    ):
        # The pages given out so far are the reserve's end up to the next
        # free one. A firmware that took such a table's word would read
        # the header back as data, or an erased page, or the page of data.
        def steps(nvme):
            return (yield from nvme.read_blocks(first=0, count=8))

        read = what_a_driver_does(
            steps,
            nand=lambda chip: a_nand_whose_table_cannot_be_its(
                chip, where_page_0, next_free
            ),
        )

        assert read == bytes(8 * 512)

    def test_a_drivers_first_write_goes_to_the_first_page_after_the_reserve(
        self, run_on_an_ssd
    ):
        # Nothing given out, the table says, and the next free page is
        # the header's own: a firmware that took its word would program
        # the drive's first page over the header. What is written is not
        # the page of data the image already has after the reserve.
        written = page_of(0x5A)

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=0, data=written)

        nand = run_on_an_ssd(
            script,
            nand=lambda chip: a_nand_whose_table_cannot_be_its(
                chip,
                where_page_0=lambda shared: ftl.NOWHERE,
                next_free=lambda shared: 0,
            ),
        ).nand

        assert (
            the_first_nand_page_after_the_reserve(nand)[: len(written)]
            == written
        )


def a_nand_whose_table_cannot_be_its(chip, where_page_0, next_free):
    """`chip`'s image with this drive's header and a table that is not its.

    A page of data is in the first NAND page after the reserve. The table
    says the drive's first page is in NAND page `where_page_0` and the next
    free page is `next_free`, each a function of the chip's layout.
    """
    shared = ftl.layout(
        chip.blocks,
        pages_per_block=chip.pages_per_block,
        page_size=chip.page_size,
    )
    where = (where_page_0(shared),) + (ftl.NOWHERE,) * (shared.drive_pages - 1)
    reserve = ftl.saved_reserve(
        ftl.Table(where, next_free(shared)), page_size=chip.page_size
    )
    return reserve.ljust(shared.reserve_pages * chip.page_size, b"\xff") + (
        some_data(chip.page_size // 512)
    )


@pytest.mark.platform
class TestWhenADriverShutsTheSsdDown:
    def test_the_ssd_says_its_shutdown_is_complete(self, what_a_driver_does):
        # 🐧 Linux waits for it before it switches the power off.
        def steps(nvme):
            yield from nvme.shut_down()
            return True

        assert what_a_driver_does(steps)

    def test_what_was_written_is_on_the_nand_by_the_table_it_keeps_there(
        self, run_on_an_ssd
    ):
        # 🎓 The table goes to the NAND's reserve, so that whoever reads the
        # NAND next, the firmware when it starts again, or Python, finds
        # the drive's pages where they are.
        written = some_data(24)

        def script():
            nvme = sp.NvmeHost(registers=NVME_BASE, memory=RAM_BASE)
            yield from nvme.enable()
            yield from nvme.write_blocks(first=8, data=written)
            yield from nvme.shut_down()

        nand = run_on_an_ssd(script).nand

        drive = ftl.drive_image(nand.contents, nand.component)
        assert drive[8 * 512 : 32 * 512] == written


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
    @pytest.fixture
    def identified(self, what_a_raw_host_gets):
        """The completion of an Identify, and the page it filled."""

        def run(what, namespace=0):
            def steps(host):
                completion = yield from host.admin(
                    opcode=raw_nvme.IDENTIFY,
                    namespace=namespace,
                    data=DATA,
                    dword10=what,
                )
                return completion, (yield sp.read(DATA, 4096))

            return what_a_raw_host_gets(steps)

        return run

    def test_the_controller_says_it_has_one_namespace(self, identified):
        completion, page = identified(what=0x01)

        assert completion.status == SUCCESS
        # The number of namespaces is 32 bits at offset 516.
        assert struct.unpack_from("<I", page, 516) == (1,)

    def test_the_list_of_active_namespaces_holds_namespace_one_alone(
        self, identified
    ):
        completion, page = identified(what=0x02)

        assert completion.status == SUCCESS
        assert struct.unpack_from("<II", page) == (1, 0)

    def test_namespace_two_is_an_invalid_namespace(self, identified):
        completion, _ = identified(what=0x00, namespace=2)

        assert completion.status == INVALID_NAMESPACE

    # 0x7F is not something Identify can be asked for.
    def test_something_identify_cannot_be_asked_for_is_an_invalid_field(
        self, identified
    ):
        completion, _ = identified(what=0x7F)

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
    @pytest.fixture
    def status_of(self, what_a_raw_host_gets):
        """The status of one I/O command, sent once the I/O queues exist."""

        def run(**command):
            def steps(host):
                yield from host.create_io_queues()
                return (yield from host.io(**command))

            return what_a_raw_host_gets(steps).status

        return run

    def test_a_flush_succeeds(self, status_of):
        assert status_of(opcode=raw_nvme.FLUSH, namespace=1) == SUCCESS

    # Opcode 3 is one the NVM command set does not assign.
    def test_one_the_ssd_does_not_have_is_an_invalid_opcode(self, status_of):
        assert status_of(opcode=0x03, namespace=1) == INVALID_OPCODE

    @pytest.mark.parametrize("opcode", [raw_nvme.READ, raw_nvme.WRITE])
    def test_a_read_or_a_write_of_namespace_two_is_an_invalid_namespace(
        self, status_of, opcode
    ):
        assert (
            status_of(opcode=opcode, namespace=2, data=DATA)
            == INVALID_NAMESPACE
        )

    @pytest.mark.parametrize("opcode", [raw_nvme.READ, raw_nvme.WRITE])
    def test_data_where_nothing_answers_is_a_data_transfer_error(
        self, status_of, opcode
    ):
        assert (
            status_of(opcode=opcode, namespace=1, data=NOWHERE)
            == DATA_TRANSFER_ERROR
        )


@pytest.mark.platform
class TestWhenADriverWritesMorePagesThanOneNandBlockHolds:
    # A NAND block is 64 pages, and the firmware fills the NAND a page at a
    # time, so the 65th page written is the first of the second block. 65
    # pages are 520 of the drive's blocks.
    def test_what_went_to_the_second_nand_block_is_as_it_was_written(
        self, what_a_driver_does
    ):
        written = some_data(520)

        def steps(nvme):
            yield from nvme.write_blocks(first=0, data=written)
            first_page = yield from nvme.read_blocks(first=0, count=8)
            last_page = yield from nvme.read_blocks(first=512, count=8)
            return first_page, last_page

        assert what_a_driver_does(steps, blocks=2 * BLOCKS) == (
            written[:4096],
            written[512 * 512 :],
        )


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
