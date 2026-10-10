"""The GDB spike: a debugger on each of three CPUs at once.

The platform is the host with all three firmwares: Zephyr's disk test on
the host's 64-bit CPU, the IO die's manager and the SSD's controller each
on a 32-bit CPU of their own. Each CPU is given a GDB port.

    python spikes/gdb/three_debuggers.py attach
    python spikes/gdb/three_debuggers.py frozen
    python spikes/gdb/three_debuggers.py breakpoints
    python spikes/gdb/three_debuggers.py detach
    python spikes/gdb/three_debuggers.py serve 3331 3332 3333
    python spikes/gdb/three_debuggers.py serve 0 0 0        (no debuggers)

One experiment a run: a process can build one platform. What each shows is
in README.md beside this file.
"""

import functools
import os
import pathlib
import socket
import struct
import sys
import threading
import time

REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
# The spike may use the tree's test helpers. Nothing in the tree uses it.
sys.path.insert(0, str(REPOSITORY / "tests" / "python"))
# The package runs from the tree, where the build leaves its extension.
sys.path.insert(0, str(REPOSITORY / "python"))

import socpuppet as sp  # noqa: E402
from gdb_client import GdbClient  # noqa: E402
from socpuppet.boards.cpu_kit import SRAM_BASE  # noqa: E402
from socpuppet.boards.host import RAM_BASE, host  # noqa: E402
from socpuppet.boards.manager import add_manager  # noqa: E402
from socpuppet.boards.ssd import add_ssd  # noqa: E402

IMAGES = pathlib.Path(
    os.environ.get("SOCPUPPET_FIRMWARE_DIR", REPOSITORY / "build/firmware")
)
IMAGE = {
    "host": IMAGES / "disk_access_socpuppet_host.elf",
    "manager": IMAGES / "iomgr_socpuppet_iomgr.elf",
    "ssd": IMAGES / "ssd_socpuppet_ssd.elf",
}
STARTS_AT = {"host": RAM_BASE, "manager": SRAM_BASE, "ssd": SRAM_BASE}
VERDICTS = ("PROJECT EXECUTION SUCCESSFUL", "PROJECT EXECUTION FAILED")
#: How much of each image a debugger reads back, to show whose it reached.
#: The two 32-bit images start with the same Zephyr code, so it has to be
#: enough to get to where they differ.
FINGERPRINT = 2048


class Traced(GdbClient):
    """A GdbClient that can show every packet, with SPIKE_TRACE set."""

    def __init__(self, who, port, timeout):
        super().__init__(port, timeout)
        self._who = who

    def send(self, body):
        """Send one packet, and show it."""
        if os.environ.get("SPIKE_TRACE"):
            print(f"  {self._who:8} -> {body}", flush=True)
        super().send(body)

    def _reply(self):
        reply = super()._reply()
        if os.environ.get("SPIKE_TRACE"):
            print(f"  {self._who:8} <- {reply[:60]}", flush=True)
        return reply


def free_port():
    """A TCP port nothing is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def three_cpus(ports):
    """The host with three firmwares, built, with a GDB port on each CPU."""
    board = host(
        gdb_port=ports["host"],
        drive_blocks=4096,
        manager=functools.partial(add_manager, gdb_port=ports["manager"]),
        drive=functools.partial(add_ssd, gdb_port=ports["ssd"]),
    )
    board.platform.build()
    for who, socket_ in sockets(board).items():
        board.platform.load_elf(IMAGE[who], via=socket_)
    return board


def sockets(board):
    """Each CPU's bus socket, which is how the platform is told whose."""
    return {
        "host": board.cpu.socket,
        "manager": board.manager.cpu.socket,
        "ssd": board.drive.ssd.cpu.socket,
    }


def consoles(board):
    """Each CPU's console."""
    return {
        "host": board.uart,
        "manager": board.manager.cpu_kit.uart,
        "ssd": board.drive.ssd.cpu_kit.uart,
    }


def run_to_a_verdict(board):
    """Run until the host's disk test says how it went. Returns the verdict.

    The verdict comes at 0.6 s of simulated time, and 2 s ends a run that
    never gives one.
    """

    def verdict():
        return next((v for v in VERDICTS if v in board.uart.output), None)

    board.platform.run_until(lambda: verdict() is not None, timeout=sp.ms(2000))
    return verdict()


def monitor(debugger, command):
    """GDB's `monitor <command>`: what the server printed for it."""
    reply = debugger.ask("qRcmd," + command.encode().hex())
    try:
        return bytes.fromhex(reply).decode()
    except ValueError:
        return reply


def read_memory(debugger, address, length, piece=128):
    """`length` bytes from `address`, asked for a piece at a time."""
    return b"".join(
        debugger.read_memory(address + at, min(piece, length - at))
        for at in range(0, length, piece)
    )


def target_description(debugger):
    """The XML a GDB server describes its CPU with, whole."""
    text, offset = "", 0
    while True:
        reply = debugger.ask(f"qXfer:features:read:target.xml:{offset:x},400")
        text += reply[1:]
        offset += len(reply) - 1
        if reply[0] == "l":
            return text


def architecture(xml):
    """What is between <architecture> and </architecture>."""
    start = xml.find("<architecture>")
    end = xml.find("</architecture>")
    if start < 0 or end < 0:
        return f"(none named, {len(xml)} characters of XML)"
    return xml[start + len("<architecture>") : end]


def stop_reply(debugger):
    """Wait for the server to say its CPU stopped, after a continue."""
    return debugger._reply()


def symbol(image, name):
    """The address of `name` in an ELF file's symbol table."""
    data = pathlib.Path(image).read_bytes()
    wide = data[4] == 2
    if wide:
        shoff, shentsize, shnum = (
            struct.unpack_from("<Q", data, 0x28)[0],
            *(struct.unpack_from("<HH", data, 0x3A)),
        )
    else:
        shoff, shentsize, shnum = (
            struct.unpack_from("<I", data, 0x20)[0],
            *(struct.unpack_from("<HH", data, 0x2E)),
        )
    sections = []
    for index in range(shnum):
        at = shoff + index * shentsize
        if wide:
            kind, offset, size, link = (
                struct.unpack_from("<I", data, at + 4)[0],
                *struct.unpack_from("<QQI", data, at + 0x18),
            )
        else:
            kind, offset, size, link = (
                struct.unpack_from("<I", data, at + 4)[0],
                *struct.unpack_from("<III", data, at + 0x10),
            )
        sections.append((kind, offset, size, link))
    for kind, offset, size, link in sections:
        if kind != 2:  # SHT_SYMTAB
            continue
        strings = sections[link][1]
        entry = 24 if wide else 16
        for at in range(offset, offset + size, entry):
            if wide:
                name_at, value = struct.unpack_from("<I4xQ", data, at)
            else:
                name_at, value = struct.unpack_from("<II", data, at)
            end = data.index(b"\0", strings + name_at)
            if data[strings + name_at : end].decode() == name:
                return value
    raise LookupError(f"There is no symbol {name} in {image}.")


class Log:
    """What each debugger did and when, on the wall clock, as one list."""

    def __init__(self):
        self._began = time.monotonic()
        self._lock = threading.Lock()
        self.lines = []

    def __call__(self, who, what):
        """Note that `who` did `what`, now."""
        with self._lock:
            self.lines.append((time.monotonic() - self._began, who, what))
            if os.environ.get("SPIKE_LIVE"):
                print(f"… {who:8} {what}", flush=True)

    def show(self):
        """Print everything noted, in the order it happened."""
        for when, who, what in sorted(self.lines):
            print(f"  {when:7.3f} s  {who:8} {what}")


def on_threads(sessions):
    """Start each debugger's session on a thread of its own."""
    failures = {}

    def guarded(who, session):
        try:
            session()
        except Exception as error:
            failures[who] = error
            if os.environ.get("SPIKE_LIVE"):
                print(f"… {who:8} FAILED {error!r}", flush=True)

    threads = [
        threading.Thread(target=guarded, args=each, daemon=True)
        for each in sessions.items()
    ]
    for thread in threads:
        thread.start()
    return threads, failures


def finish(threads, failures, grace=15):
    """Wait for the debuggers, and say whether every one of them finished."""
    for thread in threads:
        thread.join(grace)
    stuck = [thread for thread in threads if thread.is_alive()]
    for who, error in failures.items():
        print(f"❌ {who}'s debugger: {error!r}")
    if stuck:
        print(f"❌ {len(stuck)} debugger(s) never finished.")
    return not failures and not stuck


def attach():
    """Three debuggers, each finds its own CPU, each says continue."""
    ports = {who: free_port() for who in IMAGE}
    board = three_cpus(ports)
    platform = board.platform
    # What each CPU's memory holds where its firmware starts, read by the
    # platform through that CPU's own bus.
    loaded = {
        who: platform.peek(STARTS_AT[who], FINGERPRINT, via=socket_)
        for who, socket_ in sockets(board).items()
    }
    assert loaded["manager"] != loaded["ssd"], "The fingerprint is too short."
    log = Log()
    found = {}

    def session(who):
        debugger = Traced(who, ports[who], timeout=60)
        log(who, "attached")
        debugger.wait_for_the_cpu_to_stop()
        log(who, "its CPU has stopped")
        found[who] = {
            "pc": debugger.program_counter(),
            "memory": read_memory(debugger, STARTS_AT[who], FINGERPRINT),
            "architecture": architecture(target_description(debugger)),
            "time": monitor(debugger, "sysc print_time"),
        }
        debugger.continue_()
        log(who, "said continue")

    threads, failures = on_threads(
        {who: functools.partial(session, who) for who in IMAGE}
    )
    verdict = run_to_a_verdict(board)
    ok = finish(threads, failures)
    log.show()
    for who, saw in found.items():
        whose = [
            name for name, bytes_ in loaded.items() if bytes_ == saw["memory"]
        ]
        if not whose:
            differs = next(
                (
                    at
                    for at, (a, b) in enumerate(
                        zip(saw["memory"], loaded[who], strict=False)
                    )
                    if a != b
                ),
                None,
            )
            print(
                f"   {who}: {len(saw['memory'])} bytes read, "
                f"first differs at {differs}"
            )
        right = saw["pc"] == STARTS_AT[who] and whose == [who]
        ok = ok and right
        print(
            f"{'✅' if right else '❌'} {who:8} pc={saw['pc']:#x} "
            f"memory is {whose}'s  {saw['architecture']}  "
            f"stopped at {saw['time']!r}"
        )
    print(
        f"simulated time {platform.time / sp.ms(1):.1f} ms, verdict: {verdict}"
    )
    return ok and verdict == VERDICTS[0] and len(found) == 3


def frozen():
    """Does a stopped CPU stop the world, and the other debuggers with it?

    The first debugger to find its CPU stopped holds it there for two
    seconds of wall clock. Every debugger asks for memory as soon as it
    attaches, and the log shows when each was answered.
    """
    ports = {who: free_port() for who in IMAGE}
    board = three_cpus(ports)
    log = Log()
    first = []
    lock = threading.Lock()
    hold = 2.0

    def session(who):
        debugger = Traced(who, ports[who], timeout=60)
        log(who, "attached, asked for memory")
        debugger.wait_for_the_cpu_to_stop()
        with lock:
            first.append(who)
            mine = len(first) == 1
        at = monitor(debugger, "sysc print_time")
        log(who, f"memory answered: its CPU has stopped, at {at}")
        if mine:
            log(who, f"holds its CPU stopped for {hold} s")
            time.sleep(hold)
        debugger.continue_()
        log(who, "said continue")

    threads, failures = on_threads(
        {who: functools.partial(session, who) for who in IMAGE}
    )
    verdict = run_to_a_verdict(board)
    ok = finish(threads, failures)
    log.show()
    answered = {
        who: when
        for when, who, what in log.lines
        if what.startswith("memory answered")
    }
    held_until = next(
        when
        for when, who, what in log.lines
        if who == first[0] and what == "said continue"
    )
    waited = all(
        when >= held_until for who, when in answered.items() if who != first[0]
    )
    print(
        f"{'✅' if waited else '❌'} {first[0]} stopped first, and the others "
        f"were answered {'only after' if waited else 'BEFORE'} it continued"
    )
    print(f"order of stopping: {first}, verdict: {verdict}")
    return ok and verdict == VERDICTS[0]


def breakpoints():
    """A breakpoint in each firmware's `main`, hit, and the boot goes on."""
    ports = {who: free_port() for who in IMAGE}
    board = three_cpus(ports)
    log = Log()
    mains = {who: symbol(image, "main") for who, image in IMAGE.items()}
    hit = {}

    def session(who):
        debugger = Traced(who, ports[who], timeout=120)
        debugger.wait_for_the_cpu_to_stop()
        # Z0 is a software breakpoint. The last number is the size of the
        # instruction it replaces, which the server ignores.
        set_ = debugger.ask(f"Z0,{mains[who]:x},2")
        log(who, f"breakpoint at main ({mains[who]:#x}): {set_}")
        debugger.continue_()
        reply = stop_reply(debugger)
        hit[who] = (reply, debugger.program_counter())
        at = monitor(debugger, "sysc print_time")
        log(who, f"stopped with {reply} at pc={hit[who][1]:#x}, at {at}")
        log(who, f"clears it: {debugger.ask(f'z0,{mains[who]:x},2')}")
        debugger.continue_()
        log(who, "said continue")

    threads, failures = on_threads(
        {who: functools.partial(session, who) for who in IMAGE}
    )
    verdict = run_to_a_verdict(board)
    ok = finish(threads, failures)
    log.show()
    for who, (reply, pc) in hit.items():
        right = pc == mains[who]
        ok = ok and right
        print(f"{'✅' if right else '❌'} {who:8} {reply} pc={pc:#x}")
    print(
        f"simulated time {board.platform.time / sp.ms(1):.1f} ms, "
        f"verdict: {verdict}"
    )
    return ok and verdict == VERDICTS[0] and len(hit) == 3


def detach():
    """What a debugger that detaches leaves behind.

    And whether another can attach to the same port and carry on.
    """
    ports = {who: free_port() for who in IMAGE}
    board = three_cpus(ports)
    log = Log()
    wait = 5.0

    def session(who):
        debugger = Traced(who, ports[who], timeout=60)
        debugger.wait_for_the_cpu_to_stop()
        if who != "ssd":
            debugger.continue_()
            log(who, "said continue")
            return
        log(who, f"detaches: {debugger.ask('D')!r}, and hangs up")
        debugger.close()
        time.sleep(wait)
        said = "nothing" if not board.uart.output else "something"
        log(who, f"{wait} s later the host has printed {said}")
        again = Traced(who, ports[who], timeout=60)
        again.wait_for_the_cpu_to_stop()
        log(who, f"a second debugger attached, pc={again.program_counter():#x}")
        again.continue_()
        log(who, "the second debugger said continue")

    threads, failures = on_threads(
        {who: functools.partial(session, who) for who in IMAGE}
    )
    verdict = run_to_a_verdict(board)
    ok = finish(threads, failures)
    log.show()
    print(f"verdict: {verdict}")
    return ok and verdict == VERDICTS[0]


def serve(host_port, manager_port, ssd_port):
    """Wait on three ports for real GDBs, and say how the boot ended."""
    ports = {
        "host": int(host_port),
        "manager": int(manager_port),
        "ssd": int(ssd_port),
    }
    board = three_cpus(ports)
    print(f"listening: {ports}", flush=True)
    began = time.monotonic()
    verdict = run_to_a_verdict(board)
    print(f"the run took {time.monotonic() - began:.2f} s of wall clock")
    for who, console in consoles(board).items():
        print(f"--- {who} printed {len(console.output.splitlines())} lines")
    print(
        f"simulated time {board.platform.time / sp.ms(1):.1f} ms, "
        f"verdict: {verdict}"
    )
    return verdict == VERDICTS[0]


if __name__ == "__main__":
    experiments = {
        "attach": attach,
        "frozen": frozen,
        "breakpoints": breakpoints,
        "detach": detach,
        "serve": serve,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in experiments:
        sys.exit(f"Say which experiment: {', '.join(experiments)}.")
    missing = [str(image) for image in IMAGE.values() if not image.exists()]
    if missing:
        sys.exit(f"Build the firmware first (firmware/build.sh): {missing}")

    # ⚠️ A CPU that waits for a debugger holds the simulation's one thread,
    # and no limit in simulated time ends that. So a wall clock does.
    limit = float(os.environ.get("SPIKE_WALL_LIMIT", "180"))

    def give_up():
        """End a run that a stopped CPU is holding for ever."""
        print(f"❌ still not finished after {limit} s of wall clock")
        sys.stdout.flush()
        os._exit(2)

    watchdog = threading.Timer(limit, give_up)
    watchdog.daemon = True
    watchdog.start()
    passed = experiments[sys.argv[1]](*sys.argv[2:])
    print("✅ passed" if passed else "❌ failed")
    # The debuggers' threads may still be blocked on a socket, and the GDB
    # servers' threads never end, so leave without waiting for either.
    sys.stdout.flush()
    os._exit(0 if passed else 1)
