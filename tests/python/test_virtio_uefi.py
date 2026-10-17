"""UEFI's own virtio drivers against 🎭 the host's virtio devices.

EDK2's RISC-V image finds every `virtio,mmio` node in the devicetree it is
handed (`VirtioFdtDxe`), asks each what it is, and binds the driver for
that kind: the disk's, the network card's, the entropy device's and the
file system's are in the image. It never takes their interrupts: EDK2
polls the used rings. Each test boots OpenSBI and UEFI to `Shell>` the
quick way, as M28's do, on a host with the virtio slots, and then 🧵 Python
types at the shell.

    compute.cpu ─▶ ... ─▶ io.bus ─┬─▶ io.uart        (UEFI's console)
                                  ├─▶ io.rng.cpu    (slot 0)
                                  ├─▶ io.console.cpu (slot 1, no driver)
                                  └─▶ io.blk.cpu    (slot 2)
"""

import re

import pytest

import fat_image
from cast import UEFI_FD
from devicetree_compiler import needs_dtc
from opensbi_boots import a_host_with_opensbi, loaded_by_python
from socpuppet.boards.virtio import Virtio
from uefi_shell import plain, run_to_the_prompt, type_and_wait_for_the_prompt

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. Each
#: boot of UEFI takes most of a minute, so the tests are handed out first.
pytestmark = [needs_dtc, pytest.mark.long]

#: The disk Python hands UEFI: 1 MiB, with one file on it.
SECTORS = 2048
SPAM = b"spam, spam, spam\r\n"


def uefi_at_its_shell(firmware, *, disk=None):
    """A host with the virtio slots, booted to UEFI's `Shell>`.

    `disk` is an image for the virtio disk, put on it before the boot.
    """
    board, layout = a_host_with_opensbi(
        firmware, UEFI_FD, virtio=Virtio(blocks=SECTORS)
    )
    if disk is not None:
        board.virtio.blk.load(disk)
    loaded_by_python(board, layout, firmware)
    assert run_to_the_prompt(board), (
        f"UEFI never prompted. It said:\n{plain(board.uart.output)[-2000:]}"
    )
    return board


def as_uefi_names_it(board, device):
    """What UEFI calls the virtio device at `device`'s place.

    `VirtioFdtDxe` names each device by a vendor's hardware path whose data
    is the address of its registers, eight bytes little-endian, which the
    shell prints in hex.
    """
    [slot] = [
        each
        for each in board.platform.address_map(via=board.cpu.socket)
        if each.component == device.path
    ]
    return slot.address.to_bytes(8, "little").hex().upper()


@pytest.mark.platform
class TestWhenUefiBootsWithAFatDiskInTheVirtioSlot:
    def test_it_reads_the_file_python_put_there_and_writes_one_python_reads(
        self, firmware
    ):
        board = uefi_at_its_shell(
            firmware,
            disk=fat_image.make({"SPAM.TXT": SPAM}, sectors=SECTORS),
        )

        listed = type_and_wait_for_the_prompt(board, "ls fs0:")
        typed = type_and_wait_for_the_prompt(board, r"type fs0:\SPAM.TXT")
        type_and_wait_for_the_prompt(board, r"echo eggs >a fs0:\EGGS.TXT")

        assert re.search(r"\b18\s+SPAM\.TXT", listed)
        assert SPAM.decode() in typed
        assert fat_image.files(board.virtio.blk.contents) == {
            "SPAM.TXT": SPAM,
            "EGGS.TXT": b"eggs\r\n",
        }


@pytest.mark.platform
class TestWhenUefiBootsWithTheEntropyDeviceInItsSlot:
    def test_its_rng_protocol_is_on_the_device_in_slot_zero(self, firmware):
        board = uefi_at_its_shell(firmware)

        handles = type_and_wait_for_the_prompt(board, "dh -p Rng")

        assert re.search(r"\bRng\b", handles)
        assert as_uefi_names_it(board, board.virtio.rng) in handles
