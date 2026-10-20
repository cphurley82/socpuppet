"""Debugging firmware: a GDB client attached to the CPU.

Each CPU has a GDB server of its own: DBT-RISE's, and QEMU's on QBox's
CPU. The one-CPU tests and the host's run on whichever CPU SOCPUPPET_CPU
names, as the boot tests do; the two 32-bit CPUs of the host's manager
and SSD are DBT-RISE's whatever it says.
"""

import contextlib
import functools
import os
import re
import socket
import threading
import time

import pytest

import socpuppet as sp
from cast import LINUX_MAP
from disk_access import IMAGE as DISK_TEST
from disk_access import run_to_a_verdict
from gdb_client import GdbClient
from linux_shell import a_host_with_linux
from manager_firmware import IMAGE as MANAGER_IMAGE
from socpuppet import qemu_trace, ztest
from socpuppet.boards.cpu_kit import SRAM_BASE
from socpuppet.boards.host import RAM_BASE, host
from socpuppet.boards.manager import add_manager
from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK, add_ssd
from ssd_zephyr_firmware import IMAGE as SSD_IMAGE

RESET_VECTOR = 0x100
#: Where the far die's bus has the link's registers, when a test has a link,
#: and how long the link trains, which is after UCIe's 4 ms reset hold.
LINK_REGISTERS = 0x1001_0000
TRAINING_NS = 100_000
#: Longer than the link's reset hold and its training, after which the CPU
#: is let go and the short program runs.
PAST_THE_RELEASE = sp.ms(10)
#: How long a run with a ticking clock beside its CPU may go, in simulated
#: time: longer than any debugger's session, whose clock ticks about a
#: millisecond of it each millisecond of wall clock. The run ends at once
#: when the clock is stopped.
LONGER_THAN_A_SESSION = sp.ms(5000)
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
    (port,) = free_ports(1)
    return port


def free_ports(count):
    """`count` TCP ports nothing is listening on, no two the same.

    Each is held until all are found: one let go at once could be given
    out again for the next.
    """
    with contextlib.ExitStack() as held:
        ports = []
        for _ in range(count):
            probe = held.enter_context(socket.socket())
            probe.bind(("127.0.0.1", 0))
            ports.append(probe.getsockname()[1])
        return ports


def a_cpu(**described):
    """The 64-bit CPU SOCPUPPET_CPU names, described with `described`."""
    kinds = {cpu.implementation: cpu for cpu in (sp.DbtRiseCpu, sp.QboxCpu)}
    chosen = os.environ.get("SOCPUPPET_CPU", sp.DbtRiseCpu.implementation)
    return kinds[chosen](xlen=64, **described)


def cpu_waiting_for_a_debugger(port):
    """A CPU with a program loaded and a GDB server on `port`, built."""
    platform = sp.Platform()
    cpu = platform.add("cpu", a_cpu(reset_vector=RESET_VECTOR, gdb_port=port))
    ram = platform.add("ram", sp.Memory(size=0x1000))
    platform.connect(cpu.socket, ram.socket)
    platform.build()
    platform.poke(RESET_VECTOR, STORE_0X5A_THEN_SLEEP)
    return platform


def a_cpu_beside_a_ticking_clock(port):
    """A CPU waiting for a debugger, and a clock that keeps time moving.

    🎓 A CPU asleep in wfi with nothing else to do lets a run end at once:
    simulated time jumps to the end of it. On a board a timer is always
    counting, and a 🎭 stand-in plays its part here: it waits a millisecond
    of simulated time, then one of wall clock, over and over, so that time
    moves while a test watches, at about the pace of the wall clock.

    Returns the platform, built, and an event that stops the clock when it
    is set, after which a run with nothing left to do ends at once.
    """
    stop = threading.Event()

    def ticking():
        while not stop.is_set():
            yield sp.wait(sp.ms(1))
            time.sleep(0.001)

    platform = sp.Platform()
    cpu = platform.add("cpu", a_cpu(reset_vector=RESET_VECTOR, gdb_port=port))
    ram = platform.add("ram", sp.Memory(size=0x1000))
    clock = platform.add("clock", sp.ScriptedBusMaster(ticking))
    clocks_ram = platform.add("clocks_ram", sp.Memory(size=0x1000))
    platform.connect(cpu.socket, ram.socket)
    platform.connect(clock.socket, clocks_ram.socket)
    platform.build()
    platform.poke(RESET_VECTOR, STORE_0X5A_THEN_SLEEP, via=cpu.socket)
    return platform, stop


def run_with_a_debugger(
    platform, port, session, hang_up=GdbClient.close, run=None
):
    """Run `platform` with a debugger attached, and return what it found.

    `session` is what the debugger does: it is called with a GdbClient, on
    a thread of its own, because the CPU waits for the debugger while the
    platform runs. Whatever it does, the CPU is told to continue
    afterwards, so that the run always ends. `hang_up` is how the debugger
    leaves after that, and `run` how the platform is run meanwhile, as for
    `run_with_debuggers`.
    """
    return run_with_debuggers(
        platform, {port: session}, run=run, hang_up=hang_up
    )[port]


def run_with_debuggers(
    platform, sessions, run=None, hang_up=GdbClient.close, timeout=10
):
    """Run `platform` with a debugger on each port, and return what each found.

    `sessions` is what the debugger on each port does, as for
    `run_with_a_debugger`, and what comes back is by port too. Each
    debugger has a thread of its own, and waits for its own CPU to stop
    before its session starts. Each says continue when its session is
    over, and hangs up, with `hang_up`.

    `run` is how the platform is run meanwhile. With none it runs for ten
    microseconds, which is enough for the short program here once the
    debuggers let it go. `timeout` is how many seconds of wall clock a
    debugger waits for the server, to open its port and for each answer.
    """
    found = {}
    errors = []

    def debug(port, session):
        try:
            debugger = GdbClient(port, timeout)
        except OSError as error:
            errors.append(error)
            return
        try:
            debugger.wait_for_the_cpu_to_stop()
            found[port] = session(debugger)
        except Exception as error:
            errors.append(error)
        finally:
            # ⚠️ A CPU nobody tells to continue holds the whole run where
            # it is, and no limit in simulated time ends that.
            debugger.continue_()
            hang_up(debugger)

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
@pytest.mark.only_on_qbox(
    "an instruction trace is QEMU's, asked for through its own monitor "
    "commands, which DBT-RISE's server has not got"
)
class TestWhenADebuggerAsksQemuToLogWhatTheCpuRuns:
    def test_the_log_has_each_instruction_of_the_program_in_order(
        self, tmp_path
    ):
        log = tmp_path / "trace.log"
        port = free_port()
        platform = cpu_waiting_for_a_debugger(port)

        def session(debugger):
            debugger.monitor(f"logfile {log}")
            debugger.monitor("one-insn-per-tb on")
            debugger.monitor("log exec,nochain")

        run_with_a_debugger(platform, port, session)

        # The program's last instruction jumps back to its fourth, which
        # waits for an interrupt that never comes.
        assert qemu_trace.pcs(log.read_text()) == [
            RESET_VECTOR + 4 * step for step in range(4)
        ]


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
            pc = debugger.program_counter()
            # ⚠️ As GDB does at a stop: QEMU's CPU, told to continue with a
            # breakpoint where it is, stops there again.
            debugger.remove_breakpoint(the_store)
            return pc

        assert run_with_a_debugger(platform, port, session) == the_store

    def test_the_run_waits_while_it_is_stopped_and_ends_once_it_goes_on(self):
        # 🎓 Simulated time stands still while the debugger has the CPU:
        # a run of ten microseconds, which the program takes far less than,
        # is not over.
        port = free_port()
        platform = cpu_waiting_for_a_debugger(port)
        the_store = RESET_VECTOR + 8  # the program's third instruction
        ended = threading.Event()

        def run():
            platform.run(sp.us(10))
            ended.set()

        def session(debugger):
            debugger.set_breakpoint(the_store)
            debugger.continue_()
            debugger.wait_for_a_stop()
            # Half a second of wall clock, for a run that would end to end.
            ended_while_stopped = ended.wait(0.5)
            debugger.remove_breakpoint(the_store)
            return ended_while_stopped

        ended_while_stopped = run_with_a_debugger(
            platform, port, session, run=run
        )

        assert not ended_while_stopped
        assert platform.peek32(RESET_VECTOR + 0x200) == 0x5A


@pytest.mark.platform
class TestWhenADebuggerInterruptsACpuAsleepInWfi:
    def test_simulated_time_stands_still_while_it_is_stopped(self):
        port = free_port()
        platform, stop_the_clock = a_cpu_beside_a_ticking_clock(port)

        def session(debugger):
            try:
                debugger.continue_()
                # Ten milliseconds in, the program is long done and asleep.
                wait_for_simulated_time(platform, sp.ms(10))
                debugger.interrupt()
                return how_far_simulated_time_moves(platform, seconds=0.5)
            finally:
                stop_the_clock.set()

        moved = run_with_a_debugger(
            platform,
            port,
            session,
            run=lambda: platform.run(LONGER_THAN_A_SESSION),
        )

        assert moved == 0


def wait_for_simulated_time(platform, moment, timeout=10):
    """Wait until a platform running on another thread is at `moment`.

    `timeout` is in seconds of wall clock, after which it gives up.
    """
    deadline = time.monotonic() + timeout
    while platform.time < moment:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Simulated time is still {platform.time} ps, short of "
                f"{moment} ps, after {timeout} s."
            )
        time.sleep(0.01)


def how_far_simulated_time_moves(platform, seconds):
    """How far a platform running on another thread gets in `seconds` of
    wall clock, in the unit `sp.ns` returns."""
    start = platform.time
    time.sleep(seconds)
    return platform.time - start


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
class TestWhenADebuggerHangsUpWithAnAnswerUnread:
    def test_the_simulation_is_still_there_afterwards(self):
        port = free_port()
        platform = cpu_waiting_for_a_debugger(port)

        run_with_a_debugger(
            platform,
            port,
            lambda debugger: None,
            hang_up=GdbClient.close_with_an_answer_unread,
        )
        # The server hears of it on a thread of its own. Half a second of
        # wall clock is long enough for it to have ended the process.
        time.sleep(0.5)

        assert platform.peek32(RESET_VECTOR + 0x200) == 0x5A


@pytest.mark.platform
class TestWhenTwoCpusEachHaveAGdbPort:
    def test_each_debugger_finds_its_own_cpu_stopped_at_its_reset_vector(self):
        spams_port, eggs_port = free_ports(2)
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
        ports = free_ports(2)
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


@pytest.mark.platform
class TestWhenTwoCpusAreGivenTheSameGdbPort:
    def test_building_is_refused_and_the_error_names_both_cpus_and_the_port(
        self,
    ):
        platform = sp.Platform()
        for name in ("spam", "eggs"):
            cpu = platform.add(
                f"{name}_cpu",
                sp.DbtRiseCpu(xlen=64, reset_vector=0, gdb_port=1234),
            )
            ram = platform.add(f"{name}_ram", sp.Memory(size=0x1000))
            platform.connect(cpu.socket, ram.socket)

        with pytest.raises(ValueError, match="1234") as error:
            platform.build()

        assert "spam_cpu" in str(error.value)
        assert "eggs_cpu" in str(error.value)


def host_waiting_for_a_debugger(**described):
    """A host described with `described`, built, with the short program.

    The program goes where the host's CPU starts: these tests load no
    firmware, and once a debugger says continue the CPU runs what is
    there. ⚠️ With nothing there, QBox's CPU traps on every fetch, at an
    address nothing answers, and never yields the simulation
    (docs/models/qbox-cpu.md).
    """
    board = host(**described)
    board.platform.build()
    board.platform.poke(RAM_BASE, STORE_0X5A_THEN_SLEEP, via=board.cpu.socket)
    return board


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


def a_cpu_behind_two_system_controllers_and_a_link(port):
    """A CPU with a GDB port whose reset comes from a die-to-die link.

    🎭 A scripted manager on the far die brings the link up and lets the
    CPU go, and the link's hold reaches the CPU through two system
    controllers, one more than on the host: a stage more for the reset to
    rise through as the run starts.
    """
    platform = sp.Platform()
    compute = platform.group("compute")
    io = platform.group("io")
    link = platform.link(
        "d2d", sp.D2dLink(training_ns=TRAINING_NS), compute, io
    )
    manager = io.add(
        "cpu", sp.ScriptedBusMaster(sp.IoManager(link=LINK_REGISTERS).script)
    )
    bus = io.add("bus", sp.Router())
    platform.connect(manager.socket, bus.target)
    platform.connect(link.b.initiator, bus.add_input())
    platform.connect(link.b.irq, manager.irq)
    bus.map(link.b.sideband, base=LINK_REGISTERS)

    cpu = compute.add("cpu", a_cpu(reset_vector=RESET_VECTOR, gdb_port=port))
    ram = compute.add("ram", sp.Memory(size=0x1000))
    first = compute.add("first_syscon", sp.SystemController())
    second = compute.add("second_syscon", sp.SystemController())
    compute_bus = compute.add("bus", sp.Router())
    platform.connect(cpu.socket, compute_bus.target)
    compute_bus.map(ram.socket, base=0)
    compute_bus.map(first.socket, base=0x1000)
    compute_bus.map(second.socket, base=0x2000)
    platform.connect(link.a.reset, first.hold)
    platform.connect(first.reset, second.hold)
    platform.connect(second.reset, cpu.reset)
    platform.build()
    platform.poke(RESET_VECTOR, STORE_0X5A_THEN_SLEEP, via=cpu.socket)
    return platform


@pytest.mark.platform
class TestWhenACpusResetComesThroughALinkAndTwoSystemControllers:
    def test_a_debugger_finds_it_held_at_its_first_instruction_after_the_release(
        self,
    ):
        port = free_port()
        platform = a_cpu_behind_two_system_controllers_and_a_link(port)

        def session(debugger):
            # 💡 The link's reset hold and its training take simulated
            # time: a CPU held before its reset rose is found at time 0, or
            # the smallest step of time in.
            return debugger.program_counter(), platform.time

        pc, found_at = run_with_a_debugger(
            platform, port, session, run=lambda: platform.run(PAST_THE_RELEASE)
        )

        assert pc == RESET_VECTOR
        assert found_at >= sp.ns(TRAINING_NS)

    def test_once_the_debugger_says_continue_the_program_runs(self):
        port = free_port()
        platform = a_cpu_behind_two_system_controllers_and_a_link(port)

        run_with_a_debugger(
            platform,
            port,
            lambda debugger: None,
            run=lambda: platform.run(PAST_THE_RELEASE),
        )

        cpu = platform.port("compute.cpu.socket")
        assert platform.peek32(RESET_VECTOR + 0x200, via=cpu) == 0x5A


@pytest.mark.platform
class TestWhenTheHostBoardIsGivenAGdbPort:
    def test_a_debugger_finds_its_cpu_stopped_where_the_firmware_starts(self):
        port = free_port()
        board = host_waiting_for_a_debugger(gdb_port=port)

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
        board = host_waiting_for_a_debugger(
            gdb_port=port,
            drive_blocks=DRIVE_BLOCKS_PER_NAND_BLOCK,
            drive=add_ssd,
        )

        pc = run_with_a_debugger(
            board.platform, port, GdbClient.program_counter
        )

        assert pc == RAM_BASE

    def test_given_to_the_ssd_a_debugger_finds_the_ssds_cpu(self):
        port = free_port()
        board = host_waiting_for_a_debugger(
            drive_blocks=DRIVE_BLOCKS_PER_NAND_BLOCK,
            drive=functools.partial(add_ssd, gdb_port=port),
        )

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

    @pytest.mark.not_on_qbox(
        "`monitor sysc print_time` is a command DBT-RISE's GDB server adds; "
        "QEMU's has none for the simulation's time"
    )
    def test_each_cpu_tells_its_own_debugger_the_time_it_stopped_at(
        self, firmware
    ):
        # `monitor sysc print_time` is a command each CPU adds to its own
        # GDB server. The manager's CPU and the SSD's stop at power-on, the
        # smallest step of time in, having waited that long for a reset
        # that does not come (docs/upstream.md). The host's is held in
        # reset until the manager has brought the link up, so it stops
        # later.
        debugged = ThreeDebuggedCpus(firmware)

        found = debugged.each(
            lambda debugger: debugger.monitor("sysc print_time")
        )

        assert found["manager"] == found["ssd"] == "1 ps"
        assert re.fullmatch(r"[1-9]\d* (fs|ps|ns|us|ms|s)", found["host"])

    def test_once_every_debugger_has_said_continue_the_hosts_disk_test_passes(
        self, firmware
    ):
        debugged = ThreeDebuggedCpus(firmware)

        debugged.each(
            lambda debugger: None, run=lambda: run_to_a_verdict(debugged.board)
        )

        assert ztest.parse(debugged.board.uart.output).passed


#: How many seconds of wall clock a debugger waits for a kernel to reach
#: its breakpoint: OpenSBI's banner and the kernel's first steps are a
#: second of the CPU's time, and the interpreter with a breakpoint set is
#: slow.
KERNEL_ANSWERS_WITHIN = 120


@pytest.mark.platform
class TestWhenADebuggerIsAttachedToABootingKernel:
    """🐧 A debugger on the host with the kernel's symbols (`linux.map`).

    The kernel's addresses are virtual once it has turned paging on, and
    its symbols name those: a debugger that reads memory the way the CPU
    does finds the kernel's banner by its symbol.
    """

    def test_it_stops_at_start_kernel_where_the_map_says(self, firmware):
        port = free_port()
        board = a_host_with_linux(firmware, gdb_port=port)
        start_kernel = symbol(firmware(LINUX_MAP), "start_kernel")

        def session(debugger):
            debugger.set_breakpoint(start_kernel)
            debugger.continue_()
            debugger.wait_for_a_stop()
            pc = debugger.program_counter()
            debugger.remove_breakpoint(start_kernel)
            return pc

        pc = run_with_debuggers(
            board.platform,
            {port: session},
            run=lambda: board.platform.run(sp.ms(5000)),
            timeout=KERNEL_ANSWERS_WITHIN,
        )[port]

        assert pc == start_kernel

    def test_it_reads_the_kernels_banner_through_its_symbol(self, firmware):
        port = free_port()
        board = a_host_with_linux(firmware, gdb_port=port)
        start_kernel = symbol(firmware(LINUX_MAP), "start_kernel")
        linux_banner = symbol(firmware(LINUX_MAP), "linux_banner")

        def session(debugger):
            debugger.set_breakpoint(start_kernel)
            debugger.continue_()
            debugger.wait_for_a_stop()
            banner = debugger.read_memory(linux_banner, len(b"Linux version "))
            debugger.remove_breakpoint(start_kernel)
            return banner

        banner = run_with_debuggers(
            board.platform,
            {port: session},
            run=lambda: board.platform.run(sp.ms(5000)),
            timeout=KERNEL_ANSWERS_WITHIN,
        )[port]

        assert banner == b"Linux version "


def symbol(system_map, name):
    """The address `name` has in a kernel's System.map."""
    for line in system_map.read_text().splitlines():
        address, _, symbol_name = line.split(" ", 2)
        if symbol_name == name:
            return int(address, 16)
    raise AssertionError(f"{system_map} has no {name}")


def architecture(target_description):
    """What a target description has between its `architecture` tags.

    Read as text and not as XML: QEMU's description includes the rest of
    itself with `xi:include` tags whose namespace it leaves undeclared.
    """
    found = re.search(r"<architecture>(.*?)</architecture>", target_description)
    return found.group(1) if found else None


class ThreeDebuggedCpus:
    """The host with its three firmwares and a GDB port on each CPU, built.

    The CPUs are called `host`, `manager` and `ssd`.
    """

    def __init__(self, firmware):
        self.ports = dict(
            zip(("host", "manager", "ssd"), free_ports(3), strict=True)
        )
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
