"""Linux boots on OpenSBI, to a shell Python types at.

🐧 The kernel is a stock one, built by `firmware/build.py` as Linux's own
`defconfig`, with nothing of socpuppet's in it. OpenSBI's `fw_jump` starts
it 2 MiB into RAM with the devicetree the host writes, and it reads its
hardware from there: the AIA interrupt controllers, the 16550, and 🎭 the
six virtio devices. Its console is the virtio console and its root
filesystem is the virtio disk, with Alpine's mini root on it and an
inittab of ours that puts a shell on the console (`firmware/rootfs`).

It boots the quick way, with Python as the stage before OpenSBI. On
demand (`SOCPUPPET_ON_DEMAND=1`) it also boots the server's way: UEFI
finds the kernel on a disk cut up as a server's, the quick way and from
the flash.

🧵 Python is the keyboard at the console, as at UEFI's shell
(test_uefi_boots.py).
"""

import re

import pytest

import ethernet
import socpuppet as sp
from console import plain
from devicetree_compiler import needs_dtc
from linux_shell import (
    LONG_ENOUGH_THROUGH_UEFI,
    PROMPT,
    SWITCHES_OFF_WITHIN,
    a_host_with_linux,
    a_host_with_uefi_and_linux,
    run_to_the_prompt,
    type_and_wait_for_the_prompt,
)
from mt19937_64 import stream
from opensbi_boots import in_the_flash, loaded_by_python
from socpuppet.boards.host import switched_off
from socpuppet.boards.virtio import Virtio

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. A boot
#: of Linux takes seconds on QBox's hart and minutes on the interpreter, so
#: the tests are handed out first.
pytestmark = [needs_dtc, pytest.mark.long]

#: What the kernel says first, with its version: "Linux version 6.18.57".
BANNER = re.compile(r"Linux version (\d+\.\d+\.\d+)")


@pytest.fixture
def shared(tmp_path):
    """The directory of this machine the host shares with Linux."""
    return tmp_path


@pytest.fixture
def linux_at_its_prompt(firmware, shared):
    """A host that has booted OpenSBI and Linux the quick way, to the prompt.

    It shares `shared`, which Linux has not mounted.
    """
    board = a_host_with_linux(firmware, share=shared)
    prompted = run_to_the_prompt(board)
    assert prompted, (
        "Linux never prompted. OpenSBI's console:\n"
        f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
        f"{plain(board.virtio.console.output)[-3000:]}"
    )
    return board


@pytest.mark.platform
@pytest.mark.representative("linux")
class TestWhenLinuxBootsTheQuickWay:
    def test_it_says_its_version_through_opensbi_and_prompts_on_its_console(
        self, linux_at_its_prompt
    ):
        # 🎓 The kernel's first words go through OpenSBI's console on the
        # 16550 (`earlycon=sbi`), before it has found a console of its own;
        # once 🎭 the virtio console is up, everything goes there.
        board = linux_at_its_prompt
        early = plain(board.uart.output)
        console = plain(board.virtio.console.output)

        assert BANNER.search(early), f"No version. OpenSBI's console:\n{early}"
        assert PROMPT.search(console), f"No prompt. The console:\n{console}"


@pytest.mark.platform
class TestWhenPythonTypesAtLinuxsShell:
    def test_uname_names_linux_and_the_version_it_booted_saying(
        self, linux_at_its_prompt
    ):
        # 💡 The version is the one the kernel's banner gave, and not read
        # from firmware/versions.toml, which the wheel's tests run without.
        board = linux_at_its_prompt

        answer = type_and_wait_for_the_prompt(board, "uname -a")

        booted = BANNER.search(plain(board.uart.output))[1]
        assert answer.startswith(f"Linux socpuppet {booted} ")
        assert " riscv64 Linux" in answer


@pytest.mark.platform
class TestWhenPythonTypesPoweroff:
    def test_the_system_controller_switches_the_cpu_off(
        self, linux_at_its_prompt
    ):
        # 🎓 `poweroff` goes to the kernel's `syscon-poweroff` driver, which
        # writes the system controller's register, as OpenSBI's test payload
        # did by asking OpenSBI.
        board = linux_at_its_prompt
        board.virtio.console.write("poweroff\n")

        gone = board.platform.run_until(
            lambda: switched_off(board), timeout=SWITCHES_OFF_WITHIN
        )

        # ⚠️ Not the kernel's own last line, "reboot: Power down": 🎭 the
        # system controller switches the CPU off the moment the register
        # is written, before the virtio console's queue has carried it.
        assert gone, (
            f"Not switched off. The console:\n{plain(board.virtio.console.output)}"
        )


@pytest.mark.platform
class TestWhenLinuxReadsTheVirtioEntropy:
    def test_dev_hwrng_is_the_virtio_device_and_gives_the_seeded_stream(
        self, linux_at_its_prompt
    ):
        # 🎓 The kernel's own thread draws from the device first, to stir
        # into its pool, so what a reader gets is not the stream's start.
        board = linux_at_its_prompt

        source = type_and_wait_for_the_prompt(
            board, "cat /sys/class/misc/hw_random/rng_current"
        )
        read = type_and_wait_for_the_prompt(
            board, "head -c 16 /dev/hwrng | hexdump -e '16/1 \"%02x\"'"
        )

        assert source.strip() == "virtio_rng.0"
        assert bytes.fromhex(read.strip()) in stream(Virtio().seed, 1 << 20)


#: Linux's address on 🎭 the virtio network device, and Python's at the far
#: end of its wire: the documentation's own range, as Zephyr's test uses it.
ITS_ADDRESS = ethernet.ipv4("192.0.2.1")
ME = ethernet.mac("02:00:00:00:00:02")
MY_ADDRESS = ethernet.ipv4("192.0.2.2")
#: An answer to a frame comes within a moment of the CPU's time; a second
#: still ends a wait for one that never comes.
ANSWERS_A_FRAME_WITHIN = sp.ms(1000)


@pytest.mark.platform
class TestWhenPythonPingsLinux:
    def test_linux_answers_the_arp_request_and_then_the_echo(
        self, linux_at_its_prompt
    ):
        board = linux_at_its_prompt
        net = board.virtio.net
        type_and_wait_for_the_prompt(
            board, "ip addr add 192.0.2.1/24 dev eth0 && ip link set eth0 up"
        )

        net.send(
            ethernet.arp_request(
                sender=ME, sender_address=MY_ADDRESS, target=ITS_ADDRESS
            )
        )
        board.platform.run_until(
            lambda: ethernet.who_has(net.received, ITS_ADDRESS),
            timeout=ANSWERS_A_FRAME_WITHIN,
        )
        its_mac = ethernet.who_has(net.received, ITS_ADDRESS)
        assert its_mac == Virtio().mac.to_bytes(6, "big")
        net.send(
            ethernet.echo_request(
                source=(ME, MY_ADDRESS, 0),
                destination=(its_mac, ITS_ADDRESS, 0),
                payload=b"spam and eggs",
            )
        )
        board.platform.run_until(
            lambda: ethernet.echo_replies(net.received),
            timeout=ANSWERS_A_FRAME_WITHIN,
        )

        assert ethernet.echo_replies(net.received) == [b"spam and eggs"]


#: How Linux mounts 🎭 the 9P transport's share, by the tag the host gives
#: it (`Virtio().tag`), in the dialect `socpuppet.ninep` serves.
MOUNT = "mount -t 9p -o trans=virtio,version=9p2000.L socpuppet /mnt"


@pytest.mark.platform
class TestWhenLinuxMountsTheSharedDirectory:
    def test_it_reads_pythons_file_and_python_reads_the_one_it_writes(
        self, linux_at_its_prompt, shared
    ):
        (shared / "spam.txt").write_text("spam, spam, spam\n")
        board = linux_at_its_prompt

        mounted = type_and_wait_for_the_prompt(board, MOUNT)
        read = type_and_wait_for_the_prompt(board, "cat /mnt/spam.txt")
        type_and_wait_for_the_prompt(board, "echo eggs > /mnt/eggs.txt")

        assert mounted == ""
        assert read.strip() == "spam, spam, spam"
        assert (shared / "eggs.txt").read_text() == "eggs\n"


#: What the kernel says once it has found UEFI's tables, which its EFI stub
#: hands it: "efi: EFI v2.7 by EDK II".
FOUND_UEFI = re.compile(r"efi: EFI v[\d.]+ by EDK II")


@pytest.mark.on_demand("Linux booted the server's way, through UEFI")
@pytest.mark.platform
@pytest.mark.parametrize("boot", [loaded_by_python, in_the_flash])
class TestWhenUefiBootsTheKernelFromTheDisk:
    def test_the_boot_manager_starts_its_efi_stub_and_linux_prompts(
        self, firmware, boot
    ):
        # 🎓 The server's way: UEFI's boot manager finds the kernel on the
        # disk's EFI system partition, before it tries the network, and
        # the kernel finds UEFI's tables, and its root in the second
        # partition.
        board = a_host_with_uefi_and_linux(firmware, boot)

        prompted = run_to_the_prompt(board, within=LONG_ENOUGH_THROUGH_UEFI)
        assert prompted, (
            f"Linux never prompted. UEFI's console:\n"
            f"{plain(board.uart.output)[-3000:]}\nThe virtio console:\n"
            f"{plain(board.virtio.console.output)[-3000:]}"
        )
        answer = type_and_wait_for_the_prompt(board, "ls /sys/firmware/efi")

        assert FOUND_UEFI.search(plain(board.uart.output))
        assert "systab" in answer.split()
