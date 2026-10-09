"""Milestone M4's exit test: the SSD boots standalone, with its own firmware.

It is the M2 exit test again, for the third time. The host is still a
Python script, and still M2's. The drive is now a whole SSD: hardware that
keeps the queues and moves the data, a NAND to keep it in, and Zephyr on a
RISC-V core of its own making every decision.

 the host                           the SSD
 host ─▶ bus ─┬─▶ ram               endpoint ─▶ frontend ◀─▶ CPU, running Zephyr
  ▲      ▲    ├─▶ msi receiver         ▲           │            ▲
  │      │    └─▶ root complex ════════╝           ▼            ▼
  │      └─────── root complex ◀═══ endpoint ◀── uplink ◀── dma, flash ─▶ nand
  └── msi receiver

The last test puts 🎭 the stand-in drive on a second link of the same
host, gives both drives the same writes, and reads both back. The stand-in
is the reference the SSD is checked against: it answers every command
itself, in a few hundred lines with no firmware and no NAND, so the two
have little in common but the specification.
"""

import random

import pytest

import socpuppet as sp
from socpuppet.boards.drive import add_behavioral_drive
from socpuppet.boards.scripted_host import (
    ECAM_SIZE,
    MSI_BASE,
    PCIE_WINDOW_BASE,
    PCIE_WINDOW_SIZE,
    RAM_BASE,
    RAM_SIZE,
    add_scripted_host,
    bring_up_the_drive,
)
from socpuppet.boards.ssd import add_ssd, ssd

BLOCKS = 1024
# Where the host has the second root complex's two windows: after the
# first one's.
REFERENCE_ECAM = PCIE_WINDOW_BASE + PCIE_WINDOW_SIZE
REFERENCE_WINDOW = REFERENCE_ECAM + ECAM_SIZE


def run_to_the_end(platform, script_has_finished):
    """Runs until the host's script has finished, and says if it never did.

    The firmware takes a few milliseconds of simulated time to boot and
    less for a command. A second is far more than these tests need, and
    still ends a run that would never finish.
    """
    platform.run_until(script_has_finished, timeout=sp.ms(1000))
    assert script_has_finished(), "The host's script did not get to its end."


def host_and_ssd(script, image):
    """A scripted host with the SSD on its PCIe link, firmware loaded."""
    board = ssd(host=script, blocks=BLOCKS, trace=True)
    board.platform.build()
    board.platform.load_elf(image, via=board.ssd.cpu.socket)
    return board.platform


@pytest.fixture
def image(firmware):
    """The SSD's firmware: the Zephyr application in firmware/ssd."""
    return firmware("ssd_socpuppet_ssd.elf")


@pytest.mark.platform
class TestWhenAPythonHostBringsUpAnSsdThatRunsItsOwnFirmware:
    def test_the_drive_says_how_big_it_is(self, image):
        learned = []

        def script():
            nvme = yield from bring_up_the_drive()
            learned.append((yield from nvme.identify_namespace()))

        platform = host_and_ssd(script, image)

        run_to_the_end(platform, lambda: bool(learned))

        assert learned == [sp.NvmeNamespace(blocks=BLOCKS, block_size=512)]

    def test_blocks_read_back_as_they_were_written(self, image):
        # Three pages of memory, so the firmware has to follow a list of
        # them, and they do not start on a page of the NAND.
        written = bytes(index * 7 % 251 for index in range(24 * 512))
        read_back = []

        def script():
            nvme = yield from bring_up_the_drive()
            yield from nvme.write_blocks(first=13, data=written)
            read_back.append((yield from nvme.read_blocks(first=13, count=24)))

        platform = host_and_ssd(script, image)

        run_to_the_end(platform, lambda: bool(read_back))

        assert read_back == [written]

    def test_every_interrupt_arrives_as_a_message(self, image):
        done = []

        def script():
            nvme = yield from bring_up_the_drive()
            yield from nvme.identify_namespace()
            done.append(True)

        platform = host_and_ssd(script, image)

        run_to_the_end(platform, lambda: bool(done))

        # Everything the drive sends to the host crosses the traced
        # connection. A command ends with a 16-byte completion written into
        # the host's memory, and each must come with one message: a write
        # of the admin vector's number, 0, to the MSI receiver.
        writes = [
            record for record in platform.trace if record.command == "write"
        ]
        completions = [
            record
            for record in writes
            if len(record.data) == 16 and record.address >= RAM_BASE
        ]
        messages = [
            record.data for record in writes if record.address == MSI_BASE
        ]
        assert completions
        assert messages == [bytes(4)] * len(completions)


def host_with_the_ssd_and_the_reference(script, image):
    """A scripted host with two drives: the SSD, and the stand-in drive.

    Each is on a PCIe link of its own, and the host has a second root
    complex for the second. Built, with the SSD's firmware loaded.
    """
    platform = sp.Platform()
    host_group = platform.group("host")
    host = add_scripted_host(platform, script, group=host_group)
    drive = add_ssd(
        platform, host.root_complex, blocks=BLOCKS, group=platform.group("ssd")
    )
    second_link = host_group.add("reference_rc", sp.PcieRootComplex())
    host.bus.map(second_link.ecam, base=REFERENCE_ECAM, size=ECAM_SIZE)
    host.bus.map(second_link.mmio, base=REFERENCE_WINDOW, size=PCIE_WINDOW_SIZE)
    platform.connect(second_link.dma, host.bus.add_input())
    add_behavioral_drive(
        platform, second_link, blocks=BLOCKS, group=platform.group("reference")
    )
    platform.build()
    platform.load_elf(image, via=drive.cpu.socket)
    return platform


def bring_up_both_drives():
    """What the host does first: a driver for each of its two drives.

    Each driver has half of the host's memory to work in. Returns them by
    name, the SSD first.
    """
    half = RAM_SIZE // 2
    the_ssd = yield from bring_up_the_drive(memory=RAM_BASE, memory_size=half)
    the_reference = yield from bring_up_the_drive(
        ecam=REFERENCE_ECAM,
        window=REFERENCE_WINDOW,
        memory=RAM_BASE + half,
        memory_size=half,
    )
    return {"the SSD": the_ssd, "the reference": the_reference}


def some_writes(count, seed):
    """`count` writes, as (first block, data), for a drive of BLOCKS blocks.

    They are of 1 to 40 blocks, anywhere on the drive, so they overlap each
    other, start and end inside NAND pages, and some need a list of memory
    pages. The same seed gives the same writes.
    """
    chosen = random.Random(seed)
    writes = []
    for _ in range(count):
        blocks = chosen.randint(1, 40)
        first = chosen.randint(0, BLOCKS - blocks)
        writes.append((first, chosen.randbytes(blocks * 512)))
    return writes


def what_a_drive_holds_after(writes):
    """All of a drive that was new: zeros, and each write laid over what
    came before."""
    held = bytearray(BLOCKS * 512)
    for first, data in writes:
        held[first * 512 : first * 512 + len(data)] = data
    return bytes(held)


@pytest.mark.platform
class TestWhenTheSsdAndTheStandInDriveAreGivenTheSameWrites:
    def test_they_read_back_the_same_and_it_is_what_was_written(self, image):
        writes = some_writes(count=30, seed=4)
        read_back = {}

        def script():
            drives = yield from bring_up_both_drives()
            # The host uses one drive at a time, so that an interrupt can
            # only be from the drive it is waiting for.
            for name, nvme in drives.items():
                for first, data in writes:
                    yield from nvme.write_blocks(first=first, data=data)
                whole = b""
                for first in range(0, BLOCKS, 64):
                    whole += yield from nvme.read_blocks(first=first, count=64)
                read_back[name] = whole

        platform = host_with_the_ssd_and_the_reference(script, image)

        run_to_the_end(platform, lambda: len(read_back) == 2)

        assert read_back["the SSD"] == read_back["the reference"]
        assert read_back["the SSD"] == what_a_drive_holds_after(writes)
