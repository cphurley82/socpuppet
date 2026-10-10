"""🧦 `socpuppet address-map`: a description's maps, printed."""

import json
import runpy
import textwrap

from processes import run_socpuppet

#: Two bus masters with a RAM each. The first has a PLIC on its bus as
#: well, with a DMA engine's line on its source 3.
TWO_MASTERS = """
import socpuppet as sp

platform = sp.Platform()
cpu = platform.add("cpu", sp.ScriptedBusMaster())
bus = platform.add("bus", sp.Router())
ram = platform.add("ram", sp.Memory(size=0x100))
plic = platform.add("plic", sp.Plic())
dma = platform.add("dma", sp.DmaEngine())
platform.connect(cpu.socket, bus.target)
bus.map(ram.socket, base=0x8000_0000)
bus.map(plic.socket, base=0x0C00_0000)
platform.connect(dma.irq, plic.source3)
manager = platform.add("manager", sp.ScriptedBusMaster())
scratch = platform.add("scratch", sp.Memory(size=0x200))
platform.connect(manager.socket, scratch.socket)
"""


class TestWhenTheAddressMapCommandIsGivenAPlatformFile:
    def test_it_prints_each_bus_masters_map_under_the_masters_name(
        self, tmp_path
    ):
        description = description_file(tmp_path, TWO_MASTERS)

        printed = run_socpuppet("address-map", description).stdout

        assert words(
            the_section(printed, "cpu.socket"), starting="0x8000_0000"
        )[:4] == ["0x8000_0000", "256", "bytes", "ram.socket"]
        assert words(
            the_section(printed, "manager.socket"), starting="0x0000_0000"
        )[:4] == ["0x0000_0000", "512", "bytes", "scratch.socket"]

    def test_it_prints_the_interrupt_map(self, tmp_path):
        description = description_file(tmp_path, TWO_MASTERS)

        printed = run_socpuppet("address-map", description).stdout

        assert words(
            the_section(printed, "interrupt map"), starting="plic"
        ) == ["plic", "3", "dma.irq"]

    def test_what_it_prints_into_a_pipe_has_no_color_codes(self, tmp_path):
        description = description_file(tmp_path, TWO_MASTERS)

        printed = run_socpuppet("address-map", description).stdout

        assert "\x1b[" not in printed


class TestWhenTheAddressMapCommandIsToldWhoseView:
    def test_it_prints_that_map_and_no_other(self, tmp_path):
        description = description_file(tmp_path, TWO_MASTERS)

        printed = run_socpuppet(
            "address-map", description, "--via", "manager.socket"
        ).stdout

        assert "scratch.socket" in printed
        assert "ram.socket" not in printed

    def test_a_via_that_names_no_port_fails_in_one_line_that_lists_them(
        self, tmp_path
    ):
        description = description_file(tmp_path, TWO_MASTERS)

        result = run_socpuppet(
            "address-map", description, "--via", "cpu.sockit", check=False
        )

        assert result.returncode != 0
        assert "cpu.sockit" in result.stderr
        assert "socket" in result.stderr
        assert "Traceback" not in result.stderr


class TestWhenTheAddressMapCommandIsAskedForJson:
    def test_it_prints_the_maps_as_the_descriptions_json_has_them(
        self, tmp_path
    ):
        description = description_file(tmp_path, TWO_MASTERS)

        printed = json.loads(
            run_socpuppet("address-map", description, "--json").stdout
        )

        described = json.loads(
            runpy.run_path(description)["platform"].to_json()
        )
        assert printed == {
            "address_maps": described["address_maps"],
            "interrupts": described["interrupts"],
        }

    def test_with_a_view_it_has_that_map_and_no_other(self, tmp_path):
        description = description_file(tmp_path, TWO_MASTERS)

        printed = json.loads(
            run_socpuppet(
                "address-map", description, "--json", "--via", "cpu.socket"
            ).stdout
        )

        assert list(printed["address_maps"]) == ["cpu.socket"]


class TestWhenTheAddressMapCommandIsGivenAViewThatReachesNothing:
    def test_it_says_that_nothing_answers_from_there(self, tmp_path):
        description = description_file(tmp_path, TWO_MASTERS)

        # A port that accesses arrive at, and none start from.
        printed = run_socpuppet(
            "address-map", description, "--via", "scratch.socket"
        ).stdout

        assert "Nothing answers" in the_section(printed, "scratch.socket")


class TestWhenTheAddressMapCommandIsGivenAPlatformWithNoNumberedLines:
    def test_it_says_that_there_are_none(self, tmp_path):
        description = description_file(
            tmp_path,
            """
            import socpuppet as sp

            platform = sp.Platform()
            cpu = platform.add("cpu", sp.ScriptedBusMaster())
            ram = platform.add("ram", sp.Memory(size=0x100))
            platform.connect(cpu.socket, ram.socket)
            """,
        )

        printed = run_socpuppet("address-map", description).stdout

        assert "No line" in the_section(printed, "interrupt map")


class TestWhenTheAddressMapCommandIsGivenAMapThatLoops:
    def test_it_fails_in_one_line_that_says_where_it_loops(self, tmp_path):
        description = description_file(
            tmp_path,
            """
            import socpuppet as sp

            platform = sp.Platform()
            cpu = platform.add("cpu", sp.ScriptedBusMaster())
            bus = platform.add("bus", sp.Router())
            platform.connect(cpu.socket, bus.target)
            bus.map(bus.add_input(), base=0x1000, size=0x100)
            """,
        )

        result = run_socpuppet("address-map", description, check=False)

        assert result.returncode != 0
        assert "loops" in result.stderr
        assert "bus.in1" in result.stderr
        assert "Traceback" not in result.stderr


def description_file(directory, source):
    """A description file holding `source`, as the command is given one."""
    description = directory / "my_platform.py"
    description.write_text(textwrap.dedent(source))
    return str(description)


def the_section(printed, named):
    """The one section of what the command printed whose heading has `named`.

    A section is a heading, a blank line, and what is under it.
    """
    (section,) = (
        section
        for section in printed.split("\n\n🧦 ")
        if named in section.splitlines()[0]
    )
    return section


def words(section, *, starting):
    """The words of the one line of `section` whose first is `starting`."""
    (line,) = (
        line.split()
        for line in section.splitlines()
        if line.split()[:1] == [starting]
    )
    return line
