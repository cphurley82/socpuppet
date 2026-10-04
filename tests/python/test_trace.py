import json

import pytest

import socpuppet as sp
from socpuppet.trace import TraceRecord, render, to_json_lines

A_WRITE = TraceRecord(
    time=sp.ns(10),
    source="cpu.socket",
    sink="ram.socket",
    command="write",
    address=0x10,
    data=bytes.fromhex("eeffc000"),
    ok=True,
)
A_FAILED_READ = TraceRecord(
    time=sp.ns(20),
    source="cpu.socket",
    sink="ram.socket",
    command="read",
    address=0x1000,
    data=bytes(4),
    ok=False,
)


def master_with_ram(script, trace):
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    ram = platform.add("ram", sp.Memory(size=0x100))
    platform.connect(cpu.socket, ram.socket, trace=trace)
    platform.build()
    return platform


def write_after_ten_nanoseconds():
    yield sp.wait(sp.ns(10))
    yield sp.write32(0x10, 0xC0FFEE)


@pytest.mark.platform
class TestWhenAWriteCrossesATracedConnection:
    def test_the_trace_holds_what_was_written_where_and_when(self):
        def script():
            yield sp.wait(sp.ns(10))
            yield sp.write32(0x10, 0xC0FFEE)

        platform = master_with_ram(script, trace=True)

        platform.run()

        assert platform.trace == [
            sp.TraceRecord(
                time=sp.ns(10),
                source="cpu.socket",
                sink="ram.socket",
                command="write",
                address=0x10,
                data=bytes.fromhex("eeffc000"),  # 0xC0FFEE, little-endian
                ok=True,
            )
        ]


@pytest.mark.platform
class TestWhenAWriteCrossesAConnectionThatIsNotTraced:
    def test_the_trace_stays_empty(self):
        platform = master_with_ram(write_after_ten_nanoseconds, trace=False)

        platform.run()

        assert platform.trace == []


class TestWhenATraceIsRenderedWithATimeThatIsNotAWholeNanosecond:
    def test_the_time_is_shown_as_a_fraction_of_a_nanosecond(self):
        half_a_nanosecond_in = TraceRecord(500, "cpu.socket", "ram.socket", "read", 0, bytes(4), True)

        assert "0.5 ns" in render([half_a_nanosecond_in], color=False)


class TestWhenATraceIsRenderedForATerminal:
    def test_each_record_is_a_line_with_time_command_address_data_and_ports(self):
        (line,) = render([A_WRITE], color=False).splitlines()

        for part in ("10 ns", "write", "0x00000010", "ee ff c0 00", "cpu.socket", "ram.socket"):
            assert part in line

    def test_a_failed_access_is_marked(self):
        assert "❌" in render([A_FAILED_READ], color=False)

    def test_there_are_no_color_codes_when_color_is_off(self):
        assert "\x1b[" not in render([A_WRITE, A_FAILED_READ], color=False)

    def test_there_are_color_codes_when_color_is_on(self):
        assert "\x1b[" in render([A_WRITE], color=True)


class TestWhenATraceIsWrittenAsJsonLines:
    def test_each_line_is_one_record_with_plain_fields(self):
        lines = to_json_lines([A_WRITE, A_FAILED_READ]).splitlines()

        assert [json.loads(line) for line in lines] == [
            {
                "time_ps": 10_000,
                "source": "cpu.socket",
                "sink": "ram.socket",
                "command": "write",
                "address": 0x10,
                "data": "eeffc000",
                "ok": True,
            },
            {
                "time_ps": 20_000,
                "source": "cpu.socket",
                "sink": "ram.socket",
                "command": "read",
                "address": 0x1000,
                "data": "00000000",
                "ok": False,
            },
        ]
