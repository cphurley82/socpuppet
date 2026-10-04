import os
import shutil
import subprocess
import sys
import textwrap

import pytest

import socpuppet as sp


def ram_behind_a_link_and_a_router():
    """A 64 KiB RAM at 0x8000_0000, reached through a link and then a router."""
    platform = sp.Platform()
    compute = platform.group("compute")
    io = platform.group("io")
    cpu = compute.add("cpu", sp.ScriptedBusMaster())
    link = platform.link("d2d", sp.PassThroughLink(), compute, io)
    bus = io.add("bus", sp.Router())
    ram = io.add("ram", sp.Memory(size=0x10000))
    platform.connect(cpu.socket, link.a.target)
    platform.connect(link.b.initiator, bus.target)
    bus.map(ram.socket, base=0x8000_0000)
    return platform, cpu


needs_dtc = pytest.mark.skipif(
    shutil.which("dtc") is None,
    reason="dtc (the devicetree compiler) is not installed",
)


class TestWhenAPlatformHasARamBehindALinkAndARouter:
    def test_the_devicetree_is_exactly_this_source(self):
        platform, _ = ram_behind_a_link_and_a_router()

        assert platform.devicetree() == textwrap.dedent(
            """\
            /dts-v1/;

            / {
            \t#address-cells = <2>;
            \t#size-cells = <2>;

            \tio_ram: memory@80000000 {
            \t\tdevice_type = "memory";
            \t\treg = <0x0 0x80000000 0x0 0x10000>;
            \t};
            };
            """
        )

    @needs_dtc
    def test_the_devicetree_compiler_accepts_it(self, tmp_path):
        platform, _ = ram_behind_a_link_and_a_router()

        assert dtc_errors(platform.devicetree(), tmp_path) == ""


class TestWhenAPlatformHasTwoBusMasters:
    def test_the_devicetree_is_the_view_from_the_named_one(self):
        platform, cpu = ram_behind_a_link_and_a_router()
        other_cpu = platform.add("other_cpu", sp.ScriptedBusMaster())
        other_ram = platform.add("other_ram", sp.Memory(size=0x100))
        platform.connect(other_cpu.socket, other_ram.socket)

        tree = platform.devicetree(via=cpu.socket)

        assert "io_ram" in tree
        assert "other_ram" not in tree


class TestWhenTheDevicetreeCommandIsGivenAPlatformFile:
    def test_it_prints_the_devicetree_of_the_platform_the_file_describes(
        self, tmp_path
    ):
        description = tmp_path / "my_platform.py"
        description.write_text(
            textwrap.dedent(
                """
                import socpuppet as sp

                platform = sp.Platform()
                cpu = platform.add("cpu", sp.ScriptedBusMaster())
                bus = platform.add("bus", sp.Router())
                ram = platform.add("ram", sp.Memory(size=0x100))
                platform.connect(cpu.socket, bus.target)
                bus.map(ram.socket, base=0x2000)
                """
            )
        )

        printed = run_socpuppet("devicetree", str(description))

        assert "ram: memory@2000 {" in printed


class TestWhenTheDevicetreeCommandIsGivenAFileWithNoPlatformInIt:
    def test_it_fails_and_says_what_the_file_must_define(self, tmp_path):
        empty = tmp_path / "empty.py"
        empty.write_text("")

        result = run_socpuppet_unchecked("devicetree", str(empty))

        assert result.returncode != 0
        assert "`platform`" in result.stderr


def dtc_errors(source_text, scratch):
    """Compile devicetree source with dtc and return what it complained about."""
    source = scratch / "platform.dts"
    source.write_text(source_text)
    compiled = subprocess.run(
        ["dtc", "-I", "dts", "-O", "dtb", "-o", os.devnull, str(source)],
        capture_output=True,
        text=True,
    )
    return compiled.stderr


def run_socpuppet_unchecked(*arguments):
    return subprocess.run(
        [sys.executable, "-m", "socpuppet", *arguments],
        env={"PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
    )


def run_socpuppet(*arguments):
    """Run the socpuppet command line and return what it printed."""
    result = run_socpuppet_unchecked(*arguments)
    assert result.returncode == 0, result.stderr
    return result.stdout
