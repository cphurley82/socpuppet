"""🎭 The IO die's manager, as a script: it brings the link up and lets
the compute die go."""

import pytest

import socpuppet as sp
from socpuppet import ucie
from socpuppet.ops import expect32, read32, wait, write32

#: Where the IO die's bus has the link's registers and its scratch memory.
LINK = 0x1001_0000
SCRATCH = 0x3000_0000
#: Training takes a tenth of a millisecond here. UCIe's reset hold comes
#: before it, and nothing in these tests needs to know how long that is:
#: what they wait for is the link saying it is up.
TRAINING_NS = 100_000
#: Longer than bring-up, a fault and a second bring-up take together.
LONG_ENOUGH = sp.ms(30)

FIRST = 0xC0FFEE
SECOND = 0x0DECAF


def one_write_to_the_io_dies_memory():
    """What the compute die does: reach across the link, once."""
    yield write32(SCRATCH, FIRST)


def a_write_now_and_one_later():
    """The same, and again after the link has had time to be retrained.

    The compute die is a stand-in with no view of the link: all it can do
    is wait. Ten milliseconds is longer than a retrain takes, which is
    UCIe's reset hold and then the training time again.
    """
    yield write32(SCRATCH, FIRST)
    yield wait(sp.ms(10))
    yield write32(SCRATCH, SECOND)


def break_the_link_once_the_dies_are_talking():
    """A test's hand on the hardware: something on the IO die faults the
    link, once the compute die has reached across it."""
    while (yield read32(SCRATCH)) != FIRST:
        yield wait(sp.us(10))
    yield write32(LINK + ucie.FAULT_INJECTION, 1)


def watch_for_anything_arriving_too_early():
    """A test's eyes on the IO die: nothing crosses before the link is up."""
    while not (yield read32(LINK + ucie.LINK_STATUS)) & ucie.LINK_UP:
        yield expect32(SCRATCH, 0)
        yield wait(sp.us(10))


def a_manager_and_a_compute_die(compute_script, probe_script=None, trace=False):
    """The IO die with 🎭 a scripted manager, and 🎭 a scripted compute die.

    The compute die's addresses are the IO die's own: its window onto the
    other die is the whole of its address space.
    """
    platform = sp.Platform()
    compute = platform.group("compute")
    io = platform.group("io")
    link = platform.link(
        "d2d", sp.D2dLink(training_ns=TRAINING_NS), compute, io, trace=trace
    )
    manager = io.add(
        "cpu", sp.ScriptedBusMaster(sp.IoManager(link=LINK).script)
    )
    bus = io.add("bus", sp.Router())
    scratch = io.add("scratch", sp.Memory(size=0x1000))
    platform.connect(manager.socket, bus.target)
    platform.connect(link.b.initiator, bus.add_input())
    platform.connect(link.b.irq, manager.irq)
    bus.map(link.b.sideband, base=LINK)
    bus.map(scratch.socket, base=SCRATCH)

    compute_cpu = compute.add("cpu", sp.ScriptedBusMaster(compute_script))
    platform.connect(compute_cpu.socket, link.a.target)
    platform.connect(link.a.reset, compute_cpu.reset)

    if probe_script is not None:
        probe = io.add("probe", sp.ScriptedBusMaster(probe_script))
        platform.connect(probe.socket, bus.add_input())

    platform.build()
    return platform, manager


@pytest.mark.platform
class TestWhenTheManagerHasBroughtTheLinkUp:
    def test_the_compute_die_reaches_the_io_dies_memory(self):
        platform, manager = a_manager_and_a_compute_die(
            one_write_to_the_io_dies_memory
        )

        assert platform.run_until(
            lambda: platform.peek32(SCRATCH, via=manager.socket) == FIRST,
            timeout=LONG_ENOUGH,
        )


@pytest.mark.platform
class TestWhileTheLinkIsStillComingUp:
    def test_nothing_from_the_compute_die_arrives(self):
        platform, manager = a_manager_and_a_compute_die(
            one_write_to_the_io_dies_memory,
            watch_for_anything_arriving_too_early,
        )

        # The watcher's expectation fails the run if anything lands in the
        # scratch before the link is up.
        assert platform.run_until(
            lambda: platform.peek32(SCRATCH, via=manager.socket) == FIRST,
            timeout=LONG_ENOUGH,
        )


@pytest.mark.platform
class TestWhenSomethingFaultsTheLink:
    def test_the_manager_trains_it_again_and_the_dies_carry_on(self):
        platform, manager = a_manager_and_a_compute_die(
            a_write_now_and_one_later,
            break_the_link_once_the_dies_are_talking,
        )

        assert platform.run_until(
            lambda: platform.peek32(SCRATCH, via=manager.socket) == SECOND,
            timeout=LONG_ENOUGH,
        )


@pytest.mark.platform
class TestWhenALinkIsTraced:
    def test_its_sideband_reads_as_ucies_bring_up_in_order(self):
        platform, manager = a_manager_and_a_compute_die(
            one_write_to_the_io_dies_memory, trace=True
        )
        assert platform.run_until(
            lambda: platform.peek32(SCRATCH, via=manager.socket) == FIRST,
            timeout=LONG_ENOUGH,
        )

        said = what_the_sideband_said(platform.trace)

        bring_up = [
            "{SBINIT Out of Reset}",
            "{SBINIT Done Request}",
            "{SBINIT Done Response}",
            "{MBINIT.PARAM configuration request}",
            "{MBINIT.PARAM configuration response}",
            "{MBINIT.CAL Done Request}",
            "{MBINIT.CAL Done Response}",
            "{LinkMgmt.RDI.Req.Active}",
            "{LinkMgmt.RDI.Rsp.Active}",
            f"MemoryWrite_32b {ucie.DIE_RESET:#x} = 0x0",
            "Completion, success",
        ]
        assert said[: len(bring_up)] == bring_up


def what_the_sideband_said(trace):
    """Each packet in a trace of a link, described in one line."""
    packets = (ucie.SidebandPacket.from_bytes(record.data) for record in trace)
    return [packet.description() for packet in packets if packet is not None]
