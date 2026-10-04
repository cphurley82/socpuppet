"""The M0 exit test: Python pulls the strings of a small two-die platform.

compute die                              IO die
scripted master ─▶ link endpoint ══ link endpoint ─▶ router ─▶ memory
"""

import pytest

import socpuppet as sp

RAM_BASE = 0x8000_0000


def two_die_platform(script):
    platform = sp.Platform()
    compute = platform.group("compute")
    io = platform.group("io")
    cpu = compute.add("cpu", sp.ScriptedBusMaster(script))
    d2d = platform.link("d2d", sp.PassThroughLink(), compute, io)
    bus = io.add("bus", sp.Router())
    ram = io.add("ram", sp.Memory(size=0x1000))
    platform.connect(cpu.socket, d2d.a.target, trace=True)
    platform.connect(d2d.b.initiator, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    platform.build()
    return platform


@pytest.mark.platform
class TestWhenAPythonScriptedBusMasterUsesMemoryOnTheOtherSideOfThePassThroughLink:
    def test_it_reads_back_what_it_wrote(self):
        read_back = []

        def script():
            yield sp.write32(RAM_BASE + 0x10, 0xC0FFEE)
            read_back.append((yield sp.read32(RAM_BASE + 0x10)))

        platform = two_die_platform(script)

        platform.run()

        assert read_back == [0xC0FFEE]

    def test_every_access_is_seen_crossing_onto_the_link(self):
        def script():
            yield sp.write32(RAM_BASE + 0x10, 0xC0FFEE)
            yield sp.read32(RAM_BASE + 0x10)

        platform = two_die_platform(script)

        platform.run()

        assert [
            (record.command, record.address, record.source, record.sink)
            for record in platform.trace
        ] == [
            (
                "write",
                RAM_BASE + 0x10,
                "compute.cpu.socket",
                "compute.d2d.target",
            ),
            (
                "read",
                RAM_BASE + 0x10,
                "compute.cpu.socket",
                "compute.d2d.target",
            ),
        ]
