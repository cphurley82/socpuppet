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
                                  ├─▶ io.blk.cpu    (slot 2)
                                  ├─▶ io.net.cpu    (slot 3)
                                  └─▶ io.fs.cpu     (slot 4)
"""

import re

import pytest

import ethernet
import fat_image
import socpuppet as sp
from cast import UEFI_FD
from devicetree_compiler import needs_dtc
from opensbi_boots import a_host_with_opensbi, loaded_by_python
from socpuppet.boards.virtio import Virtio
from uefi_shell import plain, run_to_the_prompt, type_and_wait_for_the_prompt

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. Each
#: boot of UEFI takes most of a minute, so the tests are handed out first.
pytestmark = [needs_dtc, pytest.mark.long]

#: With a network device, the boot manager tries to boot over it before it
#: starts the shell (PXE over IPv4), and waits for an answer to its DHCP
#: request that nobody sends. That is 141 s of simulated time to the
#: prompt on the interpreter, against M28's 75, and 234 s on QBox's hart,
#: against its 90; this is a little under twice the longer, as M28's 150
#: is for 90.
LONG_ENOUGH_WITH_PXE = sp.ms(400_000)
#: UEFI's address on the wire, and 🎭 Python's, as its neighbour there.
ITS_ADDRESS = "192.0.2.1"
NEIGHBOUR = ethernet.Neighbour(
    mac=ethernet.mac("02:00:00:00:00:02"), address=ethernet.ipv4("192.0.2.2")
)
#: What the share Python serves is called.
TAG = "spam"
#: The disk Python hands UEFI: 1 MiB, with one file on it.
SECTORS = 2048
SPAM = b"spam, spam, spam\r\n"


def uefi_at_its_shell(firmware, *, disk=None, share=None):
    """A host with the virtio slots, booted to UEFI's `Shell>`.

    `disk` is an image for the virtio disk, put on it before the boot, and
    `share` a directory the file system device serves, by the tag `TAG`.
    """
    board, layout = a_host_with_opensbi(
        firmware,
        UEFI_FD,
        virtio=Virtio(blocks=SECTORS, tag=TAG, share=share),
    )
    if disk is not None:
        board.virtio.blk.load(disk)
    loaded_by_python(board, layout, firmware)
    assert run_to_the_prompt(board, within=LONG_ENOUGH_WITH_PXE), (
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


@pytest.mark.platform
class TestWhenUefiBootsWithTheNetworkDeviceInItsSlot:
    def test_it_shows_the_devices_mac_and_python_answers_its_ping(
        self, firmware
    ):
        board = uefi_at_its_shell(firmware)

        listed = type_and_wait_for_the_prompt(board, "ifconfig -l eth0")
        type_and_wait_for_the_prompt(
            board,
            f"ifconfig -s eth0 static {ITS_ADDRESS} 255.255.255.0 192.0.2.2",
        )
        pinged = type_and_wait_for_the_prompt(
            board,
            "ping -n 1 192.0.2.2",
            meanwhile=a_neighbour_answering(board.virtio.net),
        )

        assert "mac addr     : 02:00:5E:00:53:01" in listed
        assert re.search(r"1 packets transmitted, 1 received", pinged), pinged


def a_neighbour_answering(net):
    """A script that has `NEIGHBOUR` answer each frame UEFI sent since it
    last looked."""
    heard = len(net.received)

    def answer():
        nonlocal heard
        frames = net.received
        for answer in NEIGHBOUR.answers(frames[heard:]):
            net.send(answer)
        heard = len(frames)

    return answer


@pytest.mark.platform
class TestWhenUefiBootsWithADirectorySharedInTheVirtioSlot:
    def test_it_mounts_it_by_its_tag_reads_it_and_writes_a_file_to_it(
        self, firmware, tmp_path
    ):
        (tmp_path / "SPAM.TXT").write_bytes(SPAM)
        (tmp_path / "eggs").mkdir()
        board = uefi_at_its_shell(firmware, share=tmp_path)

        # The disk, with no file system on it, is no FSn: the share is FS0.
        mapped = type_and_wait_for_the_prompt(board, "map -r")
        volume = type_and_wait_for_the_prompt(board, "vol fs0:")
        listed = type_and_wait_for_the_prompt(board, "ls fs0:")
        typed = type_and_wait_for_the_prompt(board, r"type fs0:\SPAM.TXT")
        type_and_wait_for_the_prompt(board, r"echo eggs >a fs0:\EGGS.TXT")

        assert as_uefi_names_it(board, board.virtio.fs) in mapped
        assert f"Volume {TAG} (rw)" in volume
        # A directory's size has a comma in it from 1,000 on (4,096 on ext4).
        assert re.search(r"<DIR>\s+[\d,]+\s+eggs", listed)
        assert re.search(r"\b18\s+SPAM\.TXT", listed)
        assert SPAM.decode() in typed
        assert (tmp_path / "EGGS.TXT").read_bytes() == b"eggs\r\n"
