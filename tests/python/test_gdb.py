"""Debugging firmware: a GDB client attached to the CPU."""

import socket
import threading

import pytest

import socpuppet as sp
from gdb_client import GdbClient

RESET_VECTOR = 0x100

# The program from test_cpu.py: store the word 0x5A at 0x200 past its own
# first instruction, then sleep.
STORE_0X5A_THEN_SLEEP = b"".join(
    word.to_bytes(4, "little")
    for word in (0x00000297, 0x05A00313, 0x2062A023, 0x10500073, 0xFFDFF06F)
)


def free_port():
    """A TCP port nothing is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def cpu_waiting_for_a_debugger(port):
    """A CPU with a program loaded and a GDB server on `port`, built."""
    platform = sp.Platform()
    cpu = platform.add(
        "cpu",
        sp.DbtRiseCpu(xlen=64, reset_vector=RESET_VECTOR, gdb_port=port),
    )
    ram = platform.add("ram", sp.Memory(size=0x1000))
    platform.connect(cpu.socket, ram.socket)
    platform.build()
    platform.poke(RESET_VECTOR, STORE_0X5A_THEN_SLEEP)
    return platform


def run_with_a_debugger(platform, port, session):
    """Run `platform` with a debugger attached, and return what it found.

    `session` is what the debugger does: it is called with a GdbClient, on
    a thread of its own, because the CPU waits for the debugger while the
    platform runs. Whatever it does, the CPU is told to continue
    afterwards, so that the run always ends.
    """
    outcome = {}

    def debug():
        debugger = GdbClient(port)
        try:
            outcome["found"] = session(debugger)
        except Exception as error:
            outcome["error"] = error
        finally:
            debugger.continue_()

    thread = threading.Thread(target=debug)
    thread.start()
    # Long enough for the short program here, once the debugger lets it go.
    platform.run(sp.us(10))
    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["found"]


@pytest.mark.platform
class TestWhenADebuggerAttachesToACpuWithAGdbPort:
    def test_it_finds_the_cpu_stopped_at_its_reset_vector(self):
        port = free_port()
        platform = cpu_waiting_for_a_debugger(port)

        pc = run_with_a_debugger(platform, port, GdbClient.program_counter)

        assert pc == RESET_VECTOR

    def test_it_can_read_the_program_out_of_memory(self):
        port = free_port()
        platform = cpu_waiting_for_a_debugger(port)

        memory = run_with_a_debugger(
            platform,
            port,
            lambda debugger: debugger.read_memory(
                RESET_VECTOR, len(STORE_0X5A_THEN_SLEEP)
            ),
        )

        assert memory == STORE_0X5A_THEN_SLEEP

    def test_the_program_runs_once_the_debugger_says_continue(self):
        port = free_port()
        platform = cpu_waiting_for_a_debugger(port)

        run_with_a_debugger(platform, port, lambda debugger: None)

        assert platform.peek32(RESET_VECTOR + 0x200) == 0x5A


@pytest.mark.platform
class TestWhenASecondCpuAsksForAGdbPort:
    def test_building_is_refused_and_the_error_says_only_one_can(self):
        platform = sp.Platform()
        for name in ("first", "second"):
            cpu = platform.add(
                f"{name}_cpu",
                sp.DbtRiseCpu(xlen=64, reset_vector=0, gdb_port=free_port()),
            )
            ram = platform.add(f"{name}_ram", sp.Memory(size=0x1000))
            platform.connect(cpu.socket, ram.socket)

        with pytest.raises(ValueError, match="one CPU") as error:
            platform.build()

        assert "second_cpu" in str(error.value)


@pytest.mark.platform
class TestWhenTheHostBoardIsGivenAGdbPort:
    def test_a_debugger_finds_its_cpu_stopped_where_the_firmware_starts(self):
        from socpuppet.boards.host import RAM_BASE, host

        port = free_port()
        board = host(gdb_port=port)
        board.platform.build()

        pc = run_with_a_debugger(
            board.platform, port, GdbClient.program_counter
        )

        assert pc == RAM_BASE


@pytest.mark.platform
class TestWhenOneOfTheTwoCpusOfTheHostWithTheSsdIsGivenAGdbPort:
    """One debugger, on whichever CPU's firmware is being debugged.

    Which CPU it reaches shows in where it finds the CPU stopped: the
    host's firmware starts in its RAM, and the SSD's in its SRAM.
    """

    def test_given_to_the_host_a_debugger_finds_the_hosts_cpu(self):
        from socpuppet.boards.host import RAM_BASE, host
        from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK, add_ssd

        port = free_port()
        board = host(
            gdb_port=port,
            drive_blocks=DRIVE_BLOCKS_PER_NAND_BLOCK,
            drive=add_ssd,
        )
        board.platform.build()

        pc = run_with_a_debugger(
            board.platform, port, GdbClient.program_counter
        )

        assert pc == RAM_BASE

    def test_given_to_the_ssd_a_debugger_finds_the_ssds_cpu(self):
        import functools

        from socpuppet.boards.cpu_kit import SRAM_BASE
        from socpuppet.boards.host import host
        from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK, add_ssd

        port = free_port()
        board = host(
            drive_blocks=DRIVE_BLOCKS_PER_NAND_BLOCK,
            drive=functools.partial(add_ssd, gdb_port=port),
        )
        board.platform.build()

        pc = run_with_a_debugger(
            board.platform, port, GdbClient.program_counter
        )

        assert pc == SRAM_BASE
