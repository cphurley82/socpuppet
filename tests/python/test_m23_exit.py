"""M23's exit test: OpenSBI boots, and its test payload runs on it.

🧦 OpenSBI is the machine-mode firmware a RISC-V kernel sits on, and the
first program here that runs in supervisor mode is the one it starts. Its
`fw_jump` reads the devicetree in Linux's dialect, sets up the timer, the
console and the interrupt controllers, says so in a banner, and jumps to
its test payload, which prints through SBI's console call and then asks
to be switched off.

Each test runs both ways the host boots (`opensbi_boots`): the quick way,
with Python as the stage before, and from the flash, as silicon does.
"""

import re

import pytest

import socpuppet as sp
from cast import SBI_PAYLOAD_BIN, TEST_PAYLOAD_BIN
from devicetree_compiler import needs_dtc
from opensbi_boots import (
    MODEL,
    a_host_with_opensbi,
    in_the_flash,
    loaded_by_python,
)
from socpuppet import opensbi
from socpuppet.boards.cpu_kit import SYSCON_BASE
from socpuppet.boards.host import RAM_BASE
from socpuppet.regs import system_controller

#: OpenSBI is handed the devicetree compiled, and dtc compiles it. Each
#: boot of OpenSBI takes seconds, so the tests are handed out first.
pytestmark = [needs_dtc, pytest.mark.long]

BANNER = "OpenSBI v"
TEST_PAYLOAD_RUNNING = "Test payload running"
#: OpenSBI's boot to its payload is about a second of the CPU's time: a
#: banner of fifty lines, through a UART on the other die. From the flash
#: the ROM first checks the image's 2 MiB a byte at a time, which is four
#: seconds more.
LONG_ENOUGH = sp.ms(10_000)


@pytest.fixture(
    params=[
        pytest.param(loaded_by_python, id="loaded by Python"),
        pytest.param(in_the_flash, id="from the flash"),
    ]
)
def opensbi_with_its_test_payload(request, firmware):
    """A host that has run OpenSBI's `fw_jump` and its test payload.

    Booted each way, in turn. It is run until the payload has had its CPU
    switched off, or for `LONG_ENOUGH` if that never comes.
    """
    board, layout = a_host_with_opensbi(firmware, TEST_PAYLOAD_BIN)
    request.param(board, layout, firmware)
    board.platform.run_until(lambda: switched_off(board), timeout=LONG_ENOUGH)
    return board


@pytest.mark.platform
class TestWhenTheBootRomStartsOpenSbiFromTheFlash:
    def test_it_says_it_did_before_opensbi_says_anything(self, firmware):
        board, layout = a_host_with_opensbi(firmware, TEST_PAYLOAD_BIN)
        image = in_the_flash(board, layout, firmware)

        board.platform.run_until(
            lambda: BANNER in board.uart.output, timeout=LONG_ENOUGH
        )

        first, *_ = board.uart.output.splitlines()
        assert first == (
            f"rom: {image.name}: {len(image.payload)} bytes to "
            f"{image.load_address:#x}, jumping to {image.entry:#x}"
        )


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


#: What our payload says when it is about to ask for a reset, whichever.
ASKING = "payload: asking"


@pytest.fixture(
    params=[
        pytest.param(loaded_by_python, id="loaded by Python"),
        pytest.param(in_the_flash, id="from the flash"),
    ]
)
def our_payload_on_opensbi(request, firmware):
    """A host that has run OpenSBI and our payload until it asked to reset.

    Booted each way, in turn.
    """
    board, layout = a_host_with_opensbi(firmware, SBI_PAYLOAD_BIN)
    request.param(board, layout, firmware)
    board.platform.run_until(
        lambda: ASKING in board.uart.output, timeout=LONG_ENOUGH
    )
    return board


@pytest.mark.platform
class TestWhenOurPayloadRunsOnOpenSbi:
    """🎓 Our payload is the first program here that makes SBI's calls of its
    own accord, as a kernel will. Each line it says is one call or one
    thing OpenSBI did for it."""

    def test_it_says_so_through_sbis_console_call(self, our_payload_on_opensbi):
        assert "payload: hello from supervisor mode" in (
            our_payload_on_opensbi.uart.output
        )

    def test_it_finds_the_devicetree_where_a1_says(
        self, our_payload_on_opensbi
    ):
        assert "payload: devicetree magic 0xd00dfeed" in (
            our_payload_on_opensbi.uart.output
        )

    def test_sbis_timer_call_wakes_it_with_the_supervisors_timer_interrupt(
        self, our_payload_on_opensbi
    ):
        assert "payload: timer interrupt taken in supervisor mode" in (
            our_payload_on_opensbi.uart.output
        )

    def test_opensbi_makes_a_misaligned_load_on_its_behalf(
        self, our_payload_on_opensbi
    ):
        # The four bytes from one past the start of 11 22 33 44 55 66 77 88.
        assert "payload: misaligned load read 0x55443322" in (
            our_payload_on_opensbi.uart.output
        )

    def test_it_reads_that_the_power_came_on(self, our_payload_on_opensbi):
        assert "payload: reset cause power-on" in (
            our_payload_on_opensbi.uart.output
        )


@pytest.fixture
def our_payload_rebooted_from_the_flash(firmware):
    """A host that has run OpenSBI and our payload from its flash, until the
    payload has asked for a reboot and then to be switched off."""
    board, layout = a_host_with_opensbi(firmware, SBI_PAYLOAD_BIN)
    in_the_flash(board, layout, firmware)
    board.platform.run_until(
        lambda: switched_off(board), timeout=2 * LONG_ENOUGH
    )
    return board


@pytest.mark.platform
class TestWhenOurPayloadAsksOpenSbiForAColdRebootFromTheFlash:
    """🎓 SBI's reset call goes through OpenSBI's `syscon-reboot` to the
    system controller, which resets the CPU: the ROM starts again, copies
    OpenSBI from the flash afresh, and the payload runs a second time."""

    def test_the_rom_and_opensbi_start_twice(
        self, our_payload_rebooted_from_the_flash
    ):
        output = our_payload_rebooted_from_the_flash.uart.output
        rom_lines = [
            each for each in output.splitlines() if each.startswith("rom: ")
        ]

        assert (len(rom_lines), output.count(BANNER)) == (2, 2)

    def test_the_second_time_the_payload_reads_a_software_reset(
        self, our_payload_rebooted_from_the_flash
    ):
        assert "payload: reset cause software" in (
            our_payload_rebooted_from_the_flash.uart.output
        )

    def test_then_it_asks_to_be_switched_off_and_is(
        self, our_payload_rebooted_from_the_flash
    ):
        board = our_payload_rebooted_from_the_flash

        assert "payload: asking to be switched off" in board.uart.output
        assert switched_off(board)


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
