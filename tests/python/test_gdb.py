"""Debugging firmware: a GDB client attached to the CPU."""

import functools
import re
import socket
import threading
import time
import xml.etree.ElementTree

import pytest

import socpuppet as sp
from disk_access import IMAGE as DISK_TEST
from disk_access import run_to_a_verdict
from gdb_client import GdbClient
from manager_firmware import IMAGE as MANAGER_IMAGE
from socpuppet.boards.cpu_kit import SRAM_BASE
from socpuppet.boards.host import RAM_BASE, host
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK, add_ssd
from ssd_zephyr_firmware import IMAGE as SSD_IMAGE

RESET_VECTOR = 0x100
#: Where each of two CPUs starts, when a test has two.
RESET_VECTORS = {"spam": 0x100, "eggs": 0x200}
#: How much of a firmware image a debugger reads back. The manager's
#: image and the SSD's start with the same Zephyr code, and this gets to
#: where they differ.
FINGERPRINT = 2048

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
    return run_with_debuggers(platform, {port: session})[port]


def run_with_debuggers(platform, sessions, run=None):
    """Run `platform` with a debugger on each port, and return what each found.

    `sessions` is what the debugger on each port does, as for
    `run_with_a_debugger`, and what comes back is by port too. Each
    debugger has a thread of its own, and waits for its own CPU to stop
    before its session starts. Each says continue when its session is
    over, and hangs up.

    `run` is how the platform is run meanwhile. With none it runs for ten
    microseconds, which is enough for the short program here once the
    debuggers let it go.
    """
    found = {}
    errors = []

    def debug(port, session):
        debugger = GdbClient(port)
        try:
            debugger.wait_for_the_cpu_to_stop()
            found[port] = session(debugger)
        except Exception as error:
            errors.append(error)
        finally:
            # ⚠️ A CPU nobody tells to continue holds the whole run where
            # it is, and no limit in simulated time ends that.
            debugger.continue_()
            debugger.close()

    threads = [
        threading.Thread(target=debug, args=each) for each in sessions.items()
    ]
    for thread in threads:
        thread.start()
    if run is None:
        platform.run(sp.us(10))
    else:
        run()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]
    return found


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
class TestWhenACpuReachesABreakpoint:
    def test_the_debugger_is_told_once_and_can_then_ask_where_the_cpu_is(self):
        port = free_port()
        platform = cpu_waiting_for_a_debugger(port)
        the_store = RESET_VECTOR + 8  # the program's third instruction

        def session(debugger):
            debugger.set_breakpoint(the_store)
            debugger.continue_()
            debugger.wait_for_a_stop()
            # 💡 A server that reported the stop twice would answer this
            # question with its second report.
            return debugger.program_counter()

        assert run_with_a_debugger(platform, port, session) == the_store


@pytest.mark.platform
class TestWhenADebuggerSaysContinueAndHangsUp:
    def test_the_simulation_is_still_there_two_seconds_later(self):
        port = free_port()
        platform = cpu_waiting_for_a_debugger(port)

        run_with_a_debugger(platform, port, lambda debugger: None)
        # DBT-RISE's server once answered a continue a second late, and an
        # answer to a debugger that had gone ended the whole process. Two
        # seconds of wall clock is long enough for that to have happened.
        time.sleep(2)

        assert platform.peek32(RESET_VECTOR + 0x200) == 0x5A


@pytest.mark.platform
class TestWhenTwoCpusEachHaveAGdbPort:
    def test_each_debugger_finds_its_own_cpu_stopped_at_its_reset_vector(self):
        spams_port, eggs_port = free_port(), free_port()
        platform = two_cpus_waiting_for_debuggers(spams_port, eggs_port)

        found = run_with_debuggers(
            platform,
            dict.fromkeys([spams_port, eggs_port], GdbClient.program_counter),
        )

        assert found == {
            spams_port: RESET_VECTORS["spam"],
            eggs_port: RESET_VECTORS["eggs"],
        }

    def test_while_one_cpu_is_held_stopped_the_others_debugger_gets_no_answer(
        self,
    ):
        # A CPU stopped in its debugger keeps the simulation's one thread,
        # so the other CPU has not stopped: it has not run. Its debugger
        # asked about memory as it attached, as each does here, and is
        # answered when its own CPU is the one that is stopped.
        ports = [free_port(), free_port()]
        platform = two_cpus_waiting_for_debuggers(*ports)
        happened = []

        def hold_its_cpu_a_while(debugger):
            happened.append("a debugger was answered")
            # Long enough for the other debugger to be answered, if a
            # stopped CPU did not stop the other.
            time.sleep(0.5)
            happened.append("and let its CPU go")

        run_with_debuggers(platform, dict.fromkeys(ports, hold_its_cpu_a_while))

        assert happened == [
            "a debugger was answered",
            "and let its CPU go",
            "a debugger was answered",
            "and let its CPU go",
        ]


def two_cpus_waiting_for_debuggers(spams_port, eggs_port):
    """Two CPUs, `spam` and `eggs`, each with a program and a GDB port, built.

    Each has a memory of its own, and starts where `RESET_VECTORS` says.
    """
    ports = {"spam": spams_port, "eggs": eggs_port}
    platform = sp.Platform()
    for name, reset_vector in RESET_VECTORS.items():
        cpu = platform.add(
            f"{name}_cpu",
            sp.DbtRiseCpu(
                xlen=64, reset_vector=reset_vector, gdb_port=ports[name]
            ),
        )
        ram = platform.add(f"{name}_ram", sp.Memory(size=0x1000))
        platform.connect(cpu.socket, ram.socket)
    platform.build()
    for name, reset_vector in RESET_VECTORS.items():
        platform.poke(
            reset_vector,
            STORE_0X5A_THEN_SLEEP,
            via=platform.port(f"{name}_cpu.socket"),
        )
    return platform


@pytest.mark.platform
class TestWhenTheHostBoardIsGivenAGdbPort:
    def test_a_debugger_finds_its_cpu_stopped_where_the_firmware_starts(self):
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


@pytest.mark.platform
class TestWhenEachOfTheHostsThreeCpusHasAGdbPort:
    """A debugger on each CPU at once, each firmware loaded.

    The host's CPU is 64-bit and starts in its RAM. The manager's and the
    SSD's are 32-bit and both start in an SRAM of their own, at the same
    address.
    """

    def test_each_debugger_finds_its_own_cpu_stopped_where_its_firmware_starts(
        self, firmware
    ):
        debugged = ThreeDebuggedCpus(firmware)

        found = debugged.each(GdbClient.program_counter)

        assert found == {
            "host": RAM_BASE,
            "manager": SRAM_BASE,
            "ssd": SRAM_BASE,
        }

    def test_each_debugger_reads_its_own_cpus_firmware_out_of_memory(
        self, firmware
    ):
        debugged = ThreeDebuggedCpus(firmware)
        # What the platform finds through each CPU's own bus.
        loaded = {
            who: debugged.platform.peek(
                debugged.starts[who], FINGERPRINT, via=cpu.socket
            )
            for who, cpu in debugged.cpus.items()
        }

        found = debugged.debug(
            {
                who: functools.partial(
                    GdbClient.read_memory, address=start, length=FINGERPRINT
                )
                for who, start in debugged.starts.items()
            }
        )

        assert found == loaded
        # The two 32-bit images start with the same Zephyr code, so this
        # is what shows the manager's debugger did not reach the SSD.
        assert loaded["manager"] != loaded["ssd"]

    def test_each_debugger_is_told_which_kind_of_core_its_own_cpu_is(
        self, firmware
    ):
        debugged = ThreeDebuggedCpus(firmware)

        found = debugged.each(
            lambda debugger: architecture(debugger.target_description())
        )

        assert found == {
            "host": "riscv:rv64",
            "manager": "riscv:rv32",
            "ssd": "riscv:rv32",
        }

    def test_each_cpu_tells_its_own_debugger_the_time_it_stopped_at(
        self, firmware
    ):
        # `monitor sysc print_time` is a command each CPU adds to its own
        # GDB server. The manager's CPU and the SSD's stop at power-on.
        # The host's is held in reset until the manager has brought the
        # link up, so it stops later.
        debugged = ThreeDebuggedCpus(firmware)

        found = debugged.each(
            lambda debugger: debugger.monitor("sysc print_time")
        )

        assert found["manager"] == found["ssd"] == "0 s"
        assert re.fullmatch(r"[1-9]\d* (fs|ps|ns|us|ms|s)", found["host"])

    def test_once_every_debugger_has_said_continue_the_hosts_disk_test_passes(
        self, firmware
    ):
        debugged = ThreeDebuggedCpus(firmware)

        debugged.each(
            lambda debugger: None, run=lambda: run_to_a_verdict(debugged.board)
        )

        assert "PROJECT EXECUTION SUCCESSFUL" in debugged.board.uart.output


def architecture(target_description):
    """What a target description has between its `architecture` tags."""
    described = xml.etree.ElementTree.fromstring(target_description)
    return described.findtext("architecture")


class ThreeDebuggedCpus:
    """The host with its three firmwares and a GDB port on each CPU, built.

    The CPUs are called `host`, `manager` and `ssd`.
    """

    def __init__(self, firmware):
        self.ports = {who: free_port() for who in ("host", "manager", "ssd")}
        self.board = host(
            gdb_port=self.ports["host"],
            # 2 MiB of drive, as in the exit tests that run this disk test.
            drive_blocks=4096,
            manager=functools.partial(
                add_manager, gdb_port=self.ports["manager"]
            ),
            drive=functools.partial(add_ssd, gdb_port=self.ports["ssd"]),
        )
        self.platform = self.board.platform
        self.cpus = {
            "host": self.board.cpu,
            "manager": self.board.manager.cpu,
            "ssd": self.board.drive.ssd.cpu,
        }
        #: Where each CPU's firmware starts.
        self.starts = {
            "host": RAM_BASE,
            "manager": SRAM_BASE,
            "ssd": SRAM_BASE,
        }
        images = {
            "host": DISK_TEST,
            "manager": MANAGER_IMAGE,
            "ssd": SSD_IMAGE,
        }
        self.platform.build()
        for who, cpu in self.cpus.items():
            self.platform.load_elf(firmware(images[who]), via=cpu.socket)

    def each(self, session, run=None):
        """Run with a debugger on each CPU, all doing `session`.

        Returns what each found, by CPU. See `debug`.
        """
        return self.debug(dict.fromkeys(self.cpus, session), run)

    def debug(self, sessions, run=None):
        """Run with a debugger on each CPU, and return what each found.

        `sessions` is what each CPU's debugger does, by CPU, as for
        `run_with_debuggers`. With no `run`, the platform runs for ten
        milliseconds, which is past the 5.5 ms at which the link lets the
        host's CPU start.
        """
        found = run_with_debuggers(
            self.platform,
            {self.ports[who]: session for who, session in sessions.items()},
            run=run or (lambda: self.platform.run(sp.ms(10))),
        )
        return {who: found[self.ports[who]] for who in sessions}
