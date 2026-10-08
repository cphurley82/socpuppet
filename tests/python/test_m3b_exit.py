"""Milestone M3b's exit test: Zephyr does block I/O on the host's SSD.

The firmware is Zephyr's own test of its disk interface (its
`tests/drivers/disk/disk_access`), built by `firmware/build.sh` for the
board `socpuppet_host` with the shield `socpuppet_host_drive`. Nothing in
it knows about socpuppet. It finds the drive by scanning the PCIe bus,
starts it with Zephyr's stock NVMe driver, and reads and writes runs of
sectors at the start, the middle and the end of the drive, checking that
what it wrote is what it reads back.

Every command it sends is answered by an interrupt, and each interrupt is
a message that the drive sends up the PCIe link and that the MSI-to-PLIC
bridge puts on a line of the interrupt controller. So a pass means the
whole way there and back works, from the CPU to the drive's queues.

The firmware has a third test, of erasing, which skips itself: Zephyr's
NVMe driver does not erase.
"""

import pytest

import socpuppet as sp
from socpuppet.boards.host import host

#: What Zephyr's test framework ends with, when no test failed and when
#: one did.
VERDICTS = ("PROJECT EXECUTION SUCCESSFUL", "PROJECT EXECUTION FAILED")


@pytest.mark.platform
class TestWhenZephyrsDiskTestRunsOnTheHostWithADrive:
    def test_its_read_and_write_tests_pass(self, firmware):
        # 2 MiB. The firmware works in runs of up to 31 sectors, so any
        # drive of more than a few dozen would do.
        board = host(drive_blocks=4096)
        board.platform.build()
        board.platform.load_elf(firmware("disk_access_socpuppet_host.elf"))

        # The verdict comes at about half a second of simulated time. 2 s
        # leaves room and still ends a run that never gives one.
        gave_a_verdict = board.platform.run_until(
            lambda: any(each in board.uart.output for each in VERDICTS),
            timeout=sp.ms(2000),
        )

        assert gave_a_verdict, no_verdict(board.uart.output)
        assert "PASS - [disk_driver.test_read]" in board.uart.output
        assert "PASS - [disk_driver.test_write]" in board.uart.output


def no_verdict(output):
    """What to say when the firmware never finished, and where to look."""
    if not output:
        return (
            "The firmware printed nothing in 2 s. Zephyr starts the drive "
            "before it prints its banner, and waits for ever for an "
            "interrupt that does not come, so look at the way an interrupt "
            "takes first: the drive's MSI-X table, the MSI bridge, and the "
            "PLIC sources the devicetree names."
        )
    return f"The firmware gave no verdict in 2 s. It printed:\n{output}"
