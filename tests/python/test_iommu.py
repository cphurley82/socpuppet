"""The drive behind an IOMMU.

The host has an IOMMU between its PCIe root complex and the link to the
compute die (`host(iommu=True)`), and everything the drive sends up goes
through it. Zephyr's driver for it, in socpuppet's module, sets it up and
puts the drive in a device context before Zephyr's PCIe code lets the drive
do anything.

Zephyr's own disk test runs with the drive behind it twice: let through
untranslated, as Linux has it, and then through page tables that map the
RAM and the IMSIC's page to themselves, so that every access the drive
makes is walked, across the link. And socpuppet's test of the driver takes
a page away from the drive, and reads the fault the IOMMU reports.

🐧 Then Linux, with its root on the drive on the full bootchain's board, and
Linux's own driver for the IOMMU: it brings the IOMMU up on its wire and puts
the drive in a device context, through which the root is mounted. Linux 6.18 has
no DMA API through an IOMMU on RISC-V, so the context lets the drive through
untranslated.
"""

import pytest

from cast import SSD, boot
from console import plain
from devicetree_compiler import needs_dtc
from disk_access import assert_it_read_and_wrote, run_to_a_verdict
from link_trace import sent_to_the_compute_die
from linux_shell import (
    a_host_with_its_root_on_the_drive,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)
from socpuppet.boards.host import IO_BASE, IOMMU_OFFSET, host
from socpuppet.boards.ssd import add_ssd
from socpuppet.components import PcieRootComplex

#: Zephyr's disk test, with the drive behind the IOMMU: untranslated, and
#: through page tables.
UNTRANSLATED = "disk_access_iommu_socpuppet_host.elf"
PAGED = "disk_access_iommu_paged_socpuppet_host.elf"
#: socpuppet's test of its driver for the IOMMU.
THE_DRIVERS_TEST = "riscv_iommu_test_socpuppet_host.elf"
#: Its case that takes a page away from the drive and reads the fault.
THE_FAULT = "riscv_iommu.test_a_read_into_a_page_the_drive_may_not_write_fails_and_is_reported"

#: 2 MiB, as in test_zephyr_disk_on_the_host.py.
BLOCKS = 4096
#: The drive's requester ID, which is the IOMMU's ID for it.
DRIVE = PcieRootComplex.REQUESTER_ID

#: Where the IOMMU's registers are for the host's CPU, and those the tests
#: read: where the device directory is, and where each queue is.
IOMMU = IO_BASE + IOMMU_OFFSET
DDTP = 0x10
CQB = 0x18
FQB = 0x28
#: ddtp's mode, in bits 3:0, for a directory of one level; two and three
#: levels follow it.
ONE_LEVEL = 2
#: A device context is 32 bytes: tc, the second stage, translation
#: attributes, and fsc, the first stage, whose mode is in bits 63:60.
CONTEXT_SIZE = 32
FSC = 24
TC_V = 1
BARE = 0
SV39 = 8
PAGE = 0x1000


@pytest.fixture(params=["stand-in", "ssd"])
def host_behind_an_iommu(request, firmware):
    """Builds the host with its drive behind the IOMMU, with `image` loaded.

    Every test that asks for this runs twice: with 🎭 the stand-in drive,
    and with the SSD and its own Zephyr firmware.
    """
    with_the_ssd = request.param == "ssd"

    def build(image, *, trace=False):
        board = host(
            drive_blocks=BLOCKS,
            drive=add_ssd if with_the_ssd else None,
            iommu=True,
            trace=trace,
        )
        boot(board, firmware, host=image, ssd=SSD if with_the_ssd else None)
        return board

    return build


@pytest.mark.platform
@pytest.mark.long
class TestWhenZephyrsDiskTestRunsWithTheDriveUntranslated:
    def test_its_read_and_write_tests_pass(self, host_behind_an_iommu):
        board = host_behind_an_iommu(UNTRANSLATED)

        run_to_a_verdict(board)

        assert_it_read_and_wrote(board.uart.output)

    def test_the_drive_is_in_a_valid_context_with_no_page_tables(
        self, host_behind_an_iommu
    ):
        board = host_behind_an_iommu(UNTRANSLATED)

        run_to_a_verdict(board)

        tc, fsc = the_drives_context(board)
        assert tc & TC_V
        assert fsc >> 60 == BARE


@pytest.mark.platform
@pytest.mark.long
class TestWhenZephyrsDiskTestRunsWithTheDriveThroughPageTables:
    @pytest.mark.representative("iommu")
    def test_its_read_and_write_tests_pass(self, host_behind_an_iommu):
        board = host_behind_an_iommu(PAGED)

        run_to_a_verdict(board)

        assert_it_read_and_wrote(board.uart.output)

    def test_the_drive_is_in_a_valid_context_with_sv39_page_tables(
        self, host_behind_an_iommu
    ):
        board = host_behind_an_iommu(PAGED)

        run_to_a_verdict(board)

        tc, fsc = the_drives_context(board)
        assert tc & TC_V
        assert fsc >> 60 == SV39

    def test_its_page_tables_are_read_across_the_link_before_its_first_access(
        self, host_behind_an_iommu
    ):
        # 🎓 The page tables are on the compute die, in its RAM, and the
        # IOMMU on the IO die: so a walk shows in the link's trace, before
        # what the drive asked for. Which is why a real IOMMU caches what
        # it walked.
        board = host_behind_an_iommu(PAGED, trace=True)

        run_to_a_verdict(board)

        walked = pages_the_iommu_read_before_the_drives_first_access(board)
        assert walked & the_drives_page_tables(board)


@pytest.mark.platform
@pytest.mark.long
class TestWhenTheIommuDriversOwnTestRuns:
    def test_it_passes_with_the_fault_it_provokes(self, firmware):
        board = host(drive_blocks=BLOCKS, iommu=True)
        boot(board, firmware, host=THE_DRIVERS_TEST)

        report = run_to_a_verdict(board)

        assert report.passed, board.uart.output
        assert report.case(THE_FAULT).result == "PASS", board.uart.output


def the_drives_context(board):
    """The drive's device context, as (tc, fsc), read out of memory.

    The directory is where ddtp says, with as many levels as it says: one,
    the driver's, or three, Linux's. The drive's ID indexes each level by
    bits 23:16, 15:7 and 6:0.
    """
    ddtp = peek64(board, IOMMU + DDTP)
    levels = (ddtp & 0xF) - ONE_LEVEL + 1
    table = page_named_by(ddtp)
    for low, width in ((16, 8), (7, 9))[3 - levels :]:
        index = (DRIVE >> low) & ((1 << width) - 1)
        table = page_named_by(peek64(board, table + index * 8))
    context = table + (DRIVE & 0x7F) * CONTEXT_SIZE
    return peek64(board, context), peek64(board, context + FSC)


def the_drives_pci_address():
    """The drive's address as Linux writes it: domain, bus, device, function."""
    return f"0000:{DRIVE >> 8:02x}:{(DRIVE >> 3) & 0x1F:02x}.{DRIVE & 7}"


def the_drives_page_tables(board):
    """The pages of the drive's page tables, from its root down."""
    _, fsc = the_drives_context(board)
    root = (fsc & ((1 << 44) - 1)) * PAGE
    found = set()
    to_read = [root]
    while to_read:
        table = to_read.pop()
        found.add(table)
        entries = board.platform.peek(table, PAGE, via=board.cpu.socket)
        for at in range(0, PAGE, 8):
            entry = int.from_bytes(entries[at : at + 8], "little")
            # Valid, and pointing at a table: R, W and X are all clear.
            if entry & 1 and not entry & 0b1110:
                to_read.append(page_named_by(entry))
    return found


def pages_the_iommu_read_before_the_drives_first_access(board):
    """The pages read across the link before the drive's first access did.

    The drive's first access is the first thing to cross that is not in a
    page of the IOMMU's own.
    """
    crossed = sent_to_the_compute_die(board)
    its_own = the_iommus_own_pages(board)
    first = next(
        index
        for index, each in enumerate(crossed)
        if page_of(each.address) not in its_own
    )
    return {
        page_of(each.address)
        for each in crossed[:first]
        if each.command == "read"
    }


def the_iommus_own_pages(board):
    """What the IOMMU reads and writes of its own: its tables and queues."""
    return {
        page_named_by(peek64(board, IOMMU + DDTP)),
        page_named_by(peek64(board, IOMMU + CQB)),
        page_named_by(peek64(board, IOMMU + FQB)),
        *the_drives_page_tables(board),
    }


def page_named_by(entry):
    """The page a register or a table entry names in bits 53:10."""
    return ((entry >> 10) & ((1 << 44) - 1)) * PAGE


def page_of(address):
    return address & ~(PAGE - 1)


def peek64(board, address):
    return int.from_bytes(
        board.platform.peek(address, 8, via=board.cpu.socket), "little"
    )


@pytest.fixture(scope="class")
def linux_behind_an_iommu(firmware):
    """The full bootchain's board, its drive behind the IOMMU, at Linux's shell.

    🐧 Linux's root is on the drive, and Linux's own driver for the IOMMU,
    `riscv-iommu`, brings it up and puts the drive in a device context.
    """
    board = a_host_with_its_root_on_the_drive(firmware, iommu=True)
    prompted = run_to_the_prompt(board)
    assert prompted, (
        "Linux never prompted. OpenSBI's console:\n"
        f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
        f"{plain(board.virtio.console.output)[-3000:]}"
    )
    return board


@needs_dtc
@pytest.mark.platform(scope="class")
@pytest.mark.long
class TestWhenLinuxBootsWithItsRootOnTheDriveBehindTheIommu:
    # 💡 One boot for the class: its tests look at the same booted board.
    def test_linuxs_driver_brings_the_iommu_up_on_its_wire(
        self, linux_behind_an_iommu
    ):
        dmesg = type_and_wait_for_the_prompt(linux_behind_an_iommu, "dmesg")

        assert "using wire-signaled interrupts" in dmesg

    def test_the_drive_is_in_an_iommu_group(self, linux_behind_an_iommu):
        # 🎓 A group is the devices an IOMMU cannot tell apart, which are
        # given to one domain together. The drive is alone in its own.
        members = type_and_wait_for_the_prompt(
            linux_behind_an_iommu, "ls /sys/kernel/iommu_groups/*/devices"
        )

        assert the_drives_pci_address() in members

    def test_its_root_is_the_drives_first_partition_and_nothing_was_refused(
        self, linux_behind_an_iommu
    ):
        mounts = type_and_wait_for_the_prompt(
            linux_behind_an_iommu, "cat /proc/mounts"
        )
        dmesg = type_and_wait_for_the_prompt(linux_behind_an_iommu, "dmesg")

        assert "/dev/nvme0n1p1 / ext4 rw," in mounts
        # Linux's driver says "Fault" for each record it takes.
        assert "Fault" not in dmesg

    def test_linux_gives_the_drive_a_context_with_no_page_tables(
        self, linux_behind_an_iommu
    ):
        # 🐧 Linux 6.18 has no DMA API through an IOMMU on RISC-V, so every
        # device's domain is the identity: a context with a Bare first
        # stage.
        tc, fsc = the_drives_context(linux_behind_an_iommu)

        assert tc & TC_V
        assert fsc >> 60 == BARE
