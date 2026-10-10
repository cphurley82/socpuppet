"""Milestone M7's exit test: the host across the real die-to-die link.

The host of M3 and M6 was two dies with 🎭 a stand-in between them, a
link that passes every access straight through. Here the link is the
real one (`sp.D2dLink`), which carries no traffic until it has been
trained, and the IO die has 🎭 the script for a manager to train it. The
link's end on the compute die holds the host's CPU in reset until the
manager lets it go.

Nothing is built differently for this. The host's firmware cannot tell
which link it has, so its images are the ones M3's and M6's tests run:
Zephyr's `hello_world` and its test of its disk interface.
"""

import functools
import struct

import pytest

import socpuppet as sp
from disk_access import IMAGE, run_to_a_verdict
from socpuppet import ucie
from socpuppet.boards.drive import DEVICE_ID, VECTORS, VENDOR_ID
from socpuppet.boards.host import (
    ECAM_OFFSET,
    IO_BASE,
    MSI_BASE,
    RAM_BASE,
    host,
)
from socpuppet.boards.manager import add_manager, stand_in_manager
from socpuppet.boards.ssd import add_ssd, stand_in_firmware
from socpuppet.regs import ucie_link

GREETING = "Hello World! socpuppet_host"


def a_scripted_manager():
    """🎭 The script for a manager, as `host(manager=)` takes it."""
    return functools.partial(add_manager, script=stand_in_manager().script)


@pytest.mark.platform
class TestWhenZephyrsHelloWorldBootsOnTheHostAcrossTheRealLink:
    def test_it_prints_its_greeting_with_the_boards_name(self, firmware):
        board = host(manager=a_scripted_manager())
        board.platform.build()
        # With two bus masters, the platform has to be told whose
        # firmware an image is.
        board.platform.load_elf(
            firmware("hello_world_socpuppet_host.elf"), via=board.cpu.socket
        )

        # The link takes 5 ms to come up and the greeting a millisecond
        # more. 50 ms leaves room and still ends a run that never prints.
        board.platform.run_until(
            lambda: GREETING in board.uart.output, timeout=sp.ms(50)
        )

        assert GREETING in board.uart.output


#: How long UCIe holds a link in reset after power-on.
THE_RESET_HOLD = sp.ms(4)


@pytest.mark.platform
class TestFourMillisecondsAfterPowerOn:
    """What shows that the host across the real link starts late.

    Four milliseconds is UCIe's reset hold, so no manager can have the
    link up yet. Zephyr's `hello_world` has said all it has to say a
    millisecond after its CPU starts.
    """

    def test_a_host_with_the_stand_in_link_has_printed_its_greeting(
        self, firmware
    ):
        board = host()
        board.platform.build()
        board.platform.load_elf(firmware("hello_world_socpuppet_host.elf"))

        board.platform.run(THE_RESET_HOLD)

        assert GREETING in board.uart.output

    def test_a_host_across_the_real_link_has_printed_nothing(self, firmware):
        board = host(manager=a_scripted_manager())
        board.platform.build()
        board.platform.load_elf(
            firmware("hello_world_socpuppet_host.elf"), via=board.cpu.socket
        )

        board.platform.run(THE_RESET_HOLD)

        assert board.uart.output == ""


#: What is on the host's PCIe link.
THE_STAND_IN_DRIVE = "the stand-in drive"
THE_SSD_WITH_A_SCRIPT = "the SSD, with a script for its firmware"
THE_SSD_WITH_ZEPHYR = "the SSD, with Zephyr for its firmware"


@pytest.fixture(
    params=[THE_STAND_IN_DRIVE, THE_SSD_WITH_A_SCRIPT, THE_SSD_WITH_ZEPHYR]
)
def host_across_the_link(request, firmware):
    """The host across the real link, with a drive and every image loaded.

    The host's image is Zephyr's disk test. A test that asks for this runs
    three times, once for each thing M3b and M6 put on the host's PCIe
    link: 🎭 the stand-in drive, the SSD with 🎭 a script for its firmware,
    and the SSD with the Zephyr application of firmware/ssd on a CPU of
    its own.
    """
    drives = {
        THE_STAND_IN_DRIVE: {},
        THE_SSD_WITH_A_SCRIPT: {
            "drive": functools.partial(
                add_ssd, firmware=stand_in_firmware().script
            )
        },
        THE_SSD_WITH_ZEPHYR: {"drive": add_ssd},
    }
    # 2 MiB, as in M3b and M6.
    board = host(
        drive_blocks=4096,
        manager=a_scripted_manager(),
        **drives[request.param],
    )
    board.platform.build()
    board.platform.load_elf(firmware(IMAGE), via=board.cpu.socket)
    if request.param == THE_SSD_WITH_ZEPHYR:
        board.platform.load_elf(
            firmware("ssd_socpuppet_ssd.elf"), via=board.drive.ssd.cpu.socket
        )
    return board


@pytest.mark.platform
class TestWhenZephyrsDiskTestRunsOnTheHostAcrossTheRealLink:
    def test_its_read_and_write_tests_pass(self, host_across_the_link):
        board = host_across_the_link

        run_to_a_verdict(board)

        assert "PASS - [disk_driver.test_read]" in board.uart.output
        assert "PASS - [disk_driver.test_write]" in board.uart.output


@pytest.mark.platform
class TestWhenTheLinkIsTracedWhileZephyrsHelloWorldBoots:
    def test_neither_die_sends_the_other_anything_until_the_host_is_let_go(
        self, firmware
    ):
        # `hello_world` sets its UART up, on the other die, before half a
        # millisecond of its CPU's time has gone. Zephyr's disk test is a
        # tenth of a second getting to the other die, so it would show
        # nothing here.
        board = host(manager=a_scripted_manager(), trace=True)
        board.platform.build()
        board.platform.load_elf(
            firmware("hello_world_socpuppet_host.elf"), via=board.cpu.socket
        )

        # The manager lets the host go 5 ms after power-on, and the host
        # has said all it has to say a millisecond after it starts. In
        # 10 ms both have happened, whichever came first.
        board.platform.run(sp.ms(10))

        first_crossing = min(
            each.time
            for each in sent_to_the_io_die(board)
            + sent_to_the_compute_die(board)
        )

        assert when_the_host_was_let_go(board) < first_crossing


@pytest.fixture
def traced_disk_test(firmware):
    """Zephyr's disk test, run to its verdict with the link traced.

    🎭 The drive is the stand-in. Which drive it is makes no difference
    to the commands, completions and interrupts that cross the
    die-to-die link. An SSD cuts the data at other places.
    """
    board = host(drive_blocks=4096, manager=a_scripted_manager(), trace=True)
    board.platform.build()
    board.platform.load_elf(firmware(IMAGE), via=board.cpu.socket)
    run_to_a_verdict(board)
    return board


@pytest.mark.platform
class TestWhenTheLinkIsTracedWhileZephyrsDiskTestRuns:
    def test_the_host_finds_its_drive_by_configuration_reads_to_the_io_die(
        self, traced_disk_test
    ):
        board = traced_disk_test

        # The first register of a function's configuration space says who
        # made it and which device it is, and the drive is the first
        # function in the window.
        answers = {
            each.data
            for each in sent_to_the_io_die(board)
            if each.command == "read" and each.address == ECAM_OFFSET
        }

        assert answers == {struct.pack("<HH", VENDOR_ID, DEVICE_ID)}

    def test_each_command_is_a_doorbell_to_the_io_die_and_is_fetched_back(
        self, traced_disk_test
    ):
        board = traced_disk_test

        rung = submission_doorbells(board)
        fetched = [
            each
            for each in dma(board, "read")
            if len(each.data) == NVME_COMMAND_SIZE
        ]

        assert rung
        assert len(fetched) == len(rung)

    def test_each_command_is_completed_to_the_compute_die_with_an_interrupt(
        self, traced_disk_test
    ):
        board = traced_disk_test

        completed = [
            each
            for each in dma(board, "write")
            if len(each.data) == NVME_COMPLETION_SIZE
        ]
        interrupted = [
            each
            for each in sent_to_the_compute_die(board)
            if each.command == "write" and each.address == MSI_BASE
        ]

        assert len(completed) == len(submission_doorbells(board))
        assert len(interrupted) == len(completed)

    def test_the_sectors_read_and_written_cross_as_dma_both_ways(
        self, traced_disk_test
    ):
        board = traced_disk_test

        # Whatever the drive moves once the host has used its I/O queue
        # is a sector's data: what the host writes to the drive is read
        # out of the host's memory, and what it reads is written into it.
        io_began = min(
            each.time for each in submission_doorbells(board, queue=IO_QUEUE)
        )
        assert any(
            len(each.data) >= SECTOR and each.time > io_began
            for each in dma(board, "read")
        )
        assert any(
            len(each.data) >= SECTOR and each.time > io_began
            for each in dma(board, "write")
        )


#: Sizes the NVMe specification gives: a command in a submission queue
#: and a completion in a completion queue.
#: ⚠️ The tests take a read of the host's memory of that size to be a
#: command fetched, and a write of that size a completion. A drive also
#: moves data in pieces, cut where a page of the host's memory ends, and
#: none of them is 64 or 16 bytes with this image. If a rebuilt image
#: ever has one that is, a count here is one too many and the link is
#: not what is wrong.
NVME_COMMAND_SIZE = 64
NVME_COMPLETION_SIZE = 16
#: A block of this drive.
SECTOR = 512
#: Where an NVMe controller's doorbells start in its registers, and how
#: much room a queue's pair of them takes: the submission queue's first,
#: four bytes each.
NVME_DOORBELLS = 0x1000
NVME_DOORBELL_PAIR = 8
#: How many pairs of queues the drive has: one for each interrupt vector,
#: the admin queues and one pair for I/O.
QUEUES = VECTORS
#: The admin queues are pair 0, so the I/O queues are pair 1.
IO_QUEUE = 1
#: Where a PCIe function's configuration space has its first base address
#: register, which is the one the drive's registers are behind.
PCI_BAR0 = 0x10


def sent_to_the_io_die(board):
    """What the compute die sent across the link's mainband.

    ⚠️ An address here is the IO die's own: the compute die's bus has
    taken the start of its window off before the access crosses.
    """
    return [
        each
        for each in board.platform.trace
        if each.source == board.link.a.peer_initiator.path
    ]


def sent_to_the_compute_die(board):
    """What the IO die sent across the link's mainband.

    An address here is one of the compute die's, which is the host's.
    """
    return [
        each
        for each in board.platform.trace
        if each.source == board.link.b.peer_initiator.path
    ]


def dma(board, command):
    """The drive's reads, or its writes, of the host's memory."""
    return [
        each
        for each in sent_to_the_compute_die(board)
        if each.command == command and each.address >= RAM_BASE
    ]


def submission_doorbells(board, queue=None):
    """The host's writes to the drive's submission queue doorbells.

    Each is the host saying that a queue has one more command in it:
    `queue`, or any queue if none is named. Zephyr chose where the
    drive's registers are, so that is read back from the drive, as the
    host's CPU sees it.
    """
    bar0 = board.platform.peek32(
        IO_BASE + ECAM_OFFSET + PCI_BAR0, via=board.cpu.socket
    )
    # The low four bits of a base address register say what kind it is.
    doorbells = (bar0 & ~0xF) - IO_BASE + NVME_DOORBELLS
    return [
        each
        for each in sent_to_the_io_die(board)
        if each.command == "write"
        and each.address
        in [
            doorbells + pair * NVME_DOORBELL_PAIR
            for pair in (range(QUEUES) if queue is None else [queue])
        ]
    ]


def when_the_host_was_let_go(board):
    """When the manager's write to the compute die's reset register crossed."""
    return min(
        record.time
        for record, packet in ucie.sideband_packets(board.platform.trace)
        if packet.opcode is ucie.Opcode.MEMORY_WRITE_32B
        and packet.address == ucie_link.DIE_RESET
        and not packet.data & ucie_link.DIE_RESET_ASSERTED
    )
