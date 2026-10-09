"""The M4a exit test: a Python host uses an SSD that is built like one.

It is the M2 exit test again, with the 🎭 stand-in drive swapped for the
SSD's hardware. The host is the same script, and cannot tell.

 the host                           the SSD
 host ─▶ bus ─┬─▶ ram               endpoint ─▶ frontend ◀─▶ firmware
  ▲      ▲    ├─▶ msi receiver         ▲           │            ▲
  │      │    └─▶ root complex ════════╝           ▼            ▼
  │      └─────── root complex ◀═══ endpoint ◀── uplink ◀── dma, flash ─▶ nand
  └── msi receiver

There is still no CPU anywhere: the SSD's firmware is a Python script too.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.ssd import (
    HOST_MSI_BASE,
    HOST_RAM_BASE,
    bring_up_the_drive,
    ssd,
    stand_in_firmware,
)

BLOCKS = 1024


def host_and_ssd(script):
    """A scripted host with an SSD on its PCIe link, built."""
    board = ssd(
        host=script,
        blocks=BLOCKS,
        firmware=stand_in_firmware().script,
        trace=True,
    )
    board.platform.build()
    return board.platform


@pytest.mark.platform
class TestWhenAPythonHostBringsUpAnSsdOverPcie:
    def test_the_drive_says_how_big_it_is(self):
        learned = []

        def script():
            nvme = yield from bring_up_the_drive()
            learned.append((yield from nvme.identify_namespace()))

        platform = host_and_ssd(script)

        platform.run()

        assert learned == [sp.NvmeNamespace(blocks=BLOCKS, block_size=512)]

    def test_blocks_read_back_as_they_were_written(self):
        # Three pages of memory, so the firmware has to follow a list of
        # them, and they do not start on a page of the NAND.
        written = bytes(index * 7 % 251 for index in range(24 * 512))
        read_back = []

        def script():
            nvme = yield from bring_up_the_drive()
            yield from nvme.write_blocks(first=13, data=written)
            read_back.append((yield from nvme.read_blocks(first=13, count=24)))

        platform = host_and_ssd(script)

        platform.run()

        assert read_back == [written]

    def test_every_interrupt_arrives_as_a_message(self):
        def script():
            nvme = yield from bring_up_the_drive()
            yield from nvme.identify_namespace()

        platform = host_and_ssd(script)

        platform.run()

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
            if len(record.data) == 16 and record.address >= HOST_RAM_BASE
        ]
        messages = [
            record.data for record in writes if record.address == HOST_MSI_BASE
        ]
        assert completions
        assert messages == [bytes(4)] * len(completions)
