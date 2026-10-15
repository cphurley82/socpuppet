"""M23's exit test: OpenSBI boots, and its test payload runs on it.

🧦 OpenSBI is the machine-mode firmware a RISC-V kernel sits on, and the
first program here that runs in supervisor mode is the one it starts. Its
`fw_jump` reads the devicetree in Linux's dialect, sets up the timer, the
console and the interrupt controllers, says so in a banner, and jumps to
its test payload, which prints through SBI's console call and then asks
to be switched off.

🎭 The quick tier: Python puts `fw_jump`, the payload and the devicetree in
RAM where `fw_jump` expects them, and QEMU's reset vector in the ROM hands
`fw_jump` the hart's number and the devicetree's address.
"""

import re

import pytest

import socpuppet as sp
from cast import FW_JUMP_BIN, TEST_PAYLOAD_BIN
from socpuppet import devicetree, opensbi
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.cpu_kit import SYSCON_BASE
from socpuppet.boards.host import RAM_BASE, host
from socpuppet.regs import system_controller

#: What the devicetree names the board, which OpenSBI's banner repeats.
MODEL = "socpuppet host"
BANNER = "OpenSBI v"
TEST_PAYLOAD_RUNNING = "Test payload running"
#: OpenSBI's boot to its payload is about a second of the CPU's time: a
#: banner of fifty lines, through a UART on the other die.
LONG_ENOUGH = sp.ms(3000)


@pytest.fixture
def opensbi_with_its_test_payload(firmware):
    """A host that has run OpenSBI's `fw_jump` and its test payload.

    It is run until the payload has had its CPU switched off, or for
    `LONG_ENOUGH` if that never comes.
    """
    board = host(boot=from_rom, sbi=True)
    blob = devicetree.compile(
        board.platform.devicetree(dialect="linux", model=MODEL)
    )
    layout = opensbi.lay_out(
        firmware(FW_JUMP_BIN).read_bytes(),
        firmware(TEST_PAYLOAD_BIN).read_bytes(),
        blob,
        ram=RAM_BASE,
    )
    board.platform.build()
    opensbi.load(board.platform, layout, rom=ROM_BASE, via=board.cpu.socket)
    board.platform.run_until(lambda: switched_off(board), timeout=LONG_ENOUGH)
    return board


@pytest.mark.platform
class TestWhenOpenSbiBootsWithItsTestPayload:
    def test_it_prints_its_banner(self, opensbi_with_its_test_payload):
        board = opensbi_with_its_test_payload

        assert BANNER in board.uart.output

    def test_it_names_the_platform_after_the_devicetrees_model(
        self, opensbi_with_its_test_payload
    ):
        board = opensbi_with_its_test_payload

        assert said(board, "Platform Name") == MODEL

    def test_its_console_is_the_uart_and_its_timer_the_aclint_at_10_mhz(
        self, opensbi_with_its_test_payload
    ):
        board = opensbi_with_its_test_payload

        assert said(board, "Platform Console Device") == "uart8250"
        assert said(board, "Platform Timer Device") == (
            "aclint-mtimer @ 10000000Hz"
        )

    def test_it_resets_through_the_system_controller(
        self, opensbi_with_its_test_payload
    ):
        board = opensbi_with_its_test_payload

        assert said(board, "Platform Reboot Device") == "syscon-reboot"

    def test_it_finds_the_aia_for_machine_mode(
        self, opensbi_with_its_test_payload
    ):
        # By reading `mtopi`: smaia is not in the devicetree.
        board = opensbi_with_its_test_payload

        assert "smaia" in said(board, "Boot HART ISA Extensions").split(",")

    @pytest.mark.not_on_qbox("QEMU's hart has PMP, and OpenSBI counts it")
    def test_it_finds_no_pmp(self, opensbi_with_its_test_payload):
        board = opensbi_with_its_test_payload

        assert said(board, "Boot HART PMP Count") == "0"

    def test_the_test_payload_prints_through_sbis_console_call(
        self, opensbi_with_its_test_payload
    ):
        board = opensbi_with_its_test_payload

        assert TEST_PAYLOAD_RUNNING in board.uart.output

    def test_the_payloads_shutdown_switches_the_cpu_off_and_nothing_more_is_said(
        self, opensbi_with_its_test_payload
    ):
        # The payload says its shutdown failed if the call comes back.
        board = opensbi_with_its_test_payload

        assert switched_off(board)
        assert board.uart.output.rstrip().endswith(TEST_PAYLOAD_RUNNING)

    def test_opensbi_copies_the_devicetree_to_where_it_tells_its_payload(
        self, opensbi_with_its_test_payload
    ):
        # 🎓 Out of the next stage's way, where it fixes it up for it.
        board = opensbi_with_its_test_payload

        assert said(board, "Domain0 Next Arg1") == (
            f"{RAM_BASE + opensbi.DEVICETREE_COPY_OFFSET:#018x}"
        )
        copy = board.platform.peek(
            RAM_BASE + opensbi.DEVICETREE_COPY_OFFSET, 4, via=board.cpu.socket
        )
        assert copy == bytes.fromhex("d00dfeed")


def switched_off(board):
    """Whether the host's CPU has been switched off, by its system controller."""
    power_off = SYSCON_BASE + system_controller.POWER_OFF
    return board.platform.peek32(power_off, via=board.cpu.socket) == (
        system_controller.POWER_OFF_OFF
    )


def said(board, label):
    """What OpenSBI's banner says after `label` and its colon."""
    found = re.search(
        rf"^{re.escape(label)}\s*: (.*?)\r?$", board.uart.output, re.MULTILINE
    )
    assert found is not None, f"OpenSBI said nothing of {label!r}"
    return found.group(1)
