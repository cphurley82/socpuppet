"""Zephyr's own virtio drivers against 🎭 the host's virtio devices.

The drivers nobody here wrote are the point: each image is one of Zephyr's
own tests or samples, built for `socpuppet_host` with the shield
`socpuppet_host_virtio`, which puts the devices on the host's IO die.

    compute.cpu ─▶ ... ─▶ io.bus ─┬─▶ io.uart           (the console)
                                  ├─▶ io.rng.cpu       (slot 0)
                                  └─▶ io.console.cpu   (slot 1)
    compute.ram ◀── link ◀── io.up ◀── io.rng.dma, io.console.dma
    compute.imsic ◀── link ◀── io.aplic ◀── io.rng.irq     (source 18)
                                       ◀── io.console.irq (source 19)

A second shield, `socpuppet_host_virtio_console`, makes the virtio console
Zephyr's console in place of the UART. The network device is in slot 3,
and 🧵 Python is the far end of its wire: it asks who has the echo
server's address, and sends it a datagram (`ethernet`). The file system
device is in slot 4, and Python serves it a directory of this machine
(`socpuppet.fuse`).
"""

import pytest

import ethernet
import socpuppet as sp
from cast import GREETING, boot
from socpuppet import ztest
from socpuppet.boards.host import host
from socpuppet.boards.virtio import Virtio

pytestmark = pytest.mark.long

#: Zephyr's `tests/drivers/entropy/api`, with the shield.
ENTROPY_API = "entropy_api_socpuppet_host.elf"
#: Zephyr's `samples/hello_world`, with the shield and a second one that
#: makes the virtio console Zephyr's console.
HELLO_VIRTIO_CONSOLE = "hello_virtio_console_socpuppet_host.elf"
#: Zephyr's `samples/subsys/fs/virtiofs`, with the shield and a label.
VIRTIOFS = "virtiofs_socpuppet_host.elf"
#: Zephyr's `samples/net/sockets/echo_server`, with the shield.
ECHO_SERVER = "echo_server_socpuppet_host.elf"
#: The echo server's address, from the sample's `prj.conf`, and the port it
#: echoes on; and Python's end of the wire, the peer the sample names.
ITS_ADDRESS = ethernet.ipv4("192.0.2.1")
ECHO_PORT = 4242
ME = ethernet.mac("02:00:00:00:00:02")
MY_ADDRESS = ethernet.ipv4("192.0.2.2")
#: The verdict comes well inside a second of simulated time; 2 s still
#: ends a run that never gives one.
LIMIT = sp.ms(2000)


def run_to_a_verdict(board):
    """Run until the host's firmware says how its tests went.

    Returns what it said of them, as a `socpuppet.ztest.Report`.
    """
    gave_a_verdict = board.platform.run_until(
        lambda: ztest.verdict_of(board.uart.output) is not None,
        timeout=LIMIT,
    )
    assert gave_a_verdict, (
        "The host's firmware gave no verdict in the time it was given. "
        f"It printed:\n{board.uart.output or '(nothing)'}"
    )
    return ztest.parse(board.uart.output)


@pytest.mark.platform
class TestWhenZephyrsEntropyApiTestRunsOnTheVirtioEntropyDevice:
    def test_its_one_case_passes_through_zephyrs_own_virtio_driver(
        self, firmware
    ):
        board = host(virtio=Virtio())
        boot(board, firmware, host=ENTROPY_API)

        report = run_to_a_verdict(board)

        assert report.case("entropy_api.test_entropy_get_entropy").result == (
            "PASS"
        ), f"The host's firmware printed:\n{board.uart.output}"


@pytest.mark.representative("zephyr-virtio")
@pytest.mark.platform
class TestWhenZephyrsConsoleIsTheVirtioConsole:
    def test_the_greeting_comes_through_the_virtio_console_alone(
        self, firmware
    ):
        board = host(virtio=Virtio())
        boot(board, firmware, host=HELLO_VIRTIO_CONSOLE)
        console = board.virtio.console

        greeted = board.platform.run_until(
            lambda: GREETING in console.output, timeout=LIMIT
        )

        assert greeted, (
            "No greeting came through the virtio console. It said "
            f"{console.output!r}, and the UART {board.uart.output!r}."
        )
        assert board.uart.output == ""


@pytest.mark.platform
class TestWhenZephyrsEchoServerRunsOnTheVirtioNetworkDevice:
    def test_it_says_where_it_is_and_echoes_a_datagram_python_sends(
        self, firmware
    ):
        board = host(virtio=Virtio())
        boot(board, firmware, host=ECHO_SERVER)
        net = board.virtio.net
        listening = board.platform.run_until(
            lambda: (
                "Waiting for UDP packets on port 4242 (IPv4)"
                in board.uart.output
            ),
            timeout=LIMIT,
        )
        assert listening, f"The echo server said:\n{board.uart.output}"

        net.send(
            ethernet.arp_request(
                sender=ME, sender_address=MY_ADDRESS, target=ITS_ADDRESS
            )
        )
        board.platform.run_until(
            lambda: ethernet.who_has(net.received, ITS_ADDRESS), timeout=LIMIT
        )
        its_mac = ethernet.who_has(net.received, ITS_ADDRESS)
        net.send(
            ethernet.udp(
                source=(ME, MY_ADDRESS, 5000),
                destination=(its_mac, ITS_ADDRESS, ECHO_PORT),
                payload=b"spam, spam, spam",
            )
        )
        board.platform.run_until(
            lambda: ethernet.udp_payloads(net.received, port=5000),
            timeout=LIMIT,
        )

        assert its_mac == ethernet.mac("02:00:5e:00:53:01")
        assert ethernet.udp_payloads(net.received, port=5000) == [
            b"spam, spam, spam"
        ]


@pytest.mark.platform
class TestWhenZephyrsVirtiofsSampleMountsAShareServedByPython:
    def test_it_lists_and_reads_what_python_put_there_and_makes_its_own(
        self, firmware, tmp_path
    ):
        (tmp_path / "file").write_bytes(b"spam, spam, spam\n")
        (tmp_path / "eggs").mkdir()
        (tmp_path / "eggs" / "bacon.txt").write_bytes(b"bacon")
        board = host(virtio=Virtio(share=tmp_path))
        boot(board, firmware, host=VIRTIOFS)

        # The sample makes a directory last of all.
        board.platform.run_until(
            lambda: (tmp_path / "dir_created_by_zephyr").is_dir(),
            timeout=LIMIT,
        )

        # Zephyr's console ends each line with a carriage return as well.
        console = board.uart.output.replace("\r\n", "\n")
        assert (
            "/virtiofs directory tree:\n"
            "- eggs (type=dir)\n"
            "  - bacon.txt (type=file, size=5)\n"
            "- file (type=file, size=17)\n"
        ) in console
        assert "/virtiofs/file content:\nspam, spam, spam\n" in console
        # The sample writes each string with the zero that ends it.
        assert (tmp_path / "file_created_by_zephyr").read_bytes() == (
            b"hello world\n\0"
        )
        assert (tmp_path / "dir_created_by_zephyr").is_dir()
