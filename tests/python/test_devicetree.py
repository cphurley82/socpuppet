import os
import shutil
import subprocess
import textwrap

import pytest

import socpuppet as sp
from processes import run_socpuppet


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


class TestWhenAMemoryIsMappedThroughAWindowSmallerThanItself:
    def test_its_node_gives_the_size_of_the_window(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        bus = platform.add("bus", sp.Router())
        ram = platform.add("ram", sp.Memory(size=0x10000))
        platform.connect(cpu.socket, bus.target)
        bus.map(ram.socket, base=0x8000_0000, size=0x4000)

        assert "reg = <0x0 0x80000000 0x0 0x4000>;" in platform.devicetree()


class TestWhenTheAddressMapLeadsBackToWhereItHasBeen:
    def test_the_devicetree_is_refused_and_the_error_says_where_it_loops(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        bus = platform.add("bus", sp.Router())
        platform.connect(cpu.socket, bus.target)
        bus.map(bus.add_input(), base=0x1000, size=0x100)

        with pytest.raises(ValueError, match=r"loops.*bus\.in1"):
            platform.devicetree()


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

        printed = run_socpuppet("devicetree", str(description)).stdout

        assert "ram: memory@2000 {" in printed


class TestWhenTheDevicetreeCommandIsGivenAFileWithNoPlatformInIt:
    def test_it_fails_and_says_what_the_file_must_define(self, tmp_path):
        empty = tmp_path / "empty.py"
        empty.write_text("")

        result = run_socpuppet("devicetree", str(empty), check=False)

        assert result.returncode != 0
        assert "`platform`" in result.stderr


TWO_MASTERS = """
import socpuppet as sp

platform = sp.Platform()
cpu = platform.add("cpu", sp.ScriptedBusMaster())
ram = platform.add("ram", sp.Memory(size=0x100))
platform.connect(cpu.socket, ram.socket)
other_cpu = platform.add("other_cpu", sp.ScriptedBusMaster())
other_ram = platform.add("other_ram", sp.Memory(size=0x200))
platform.connect(other_cpu.socket, other_ram.socket)
"""


def description_file(directory, source):
    """A description file holding `source`, as the command is given one."""
    description = directory / "my_platform.py"
    description.write_text(textwrap.dedent(source))
    return str(description)


class TestWhenTheDevicetreeCommandIsGivenAPlatformWithTwoBusMasters:
    def test_via_says_whose_view_to_print(self, tmp_path):
        description = description_file(tmp_path, TWO_MASTERS)

        printed = run_socpuppet(
            "devicetree", description, "--via", "other_cpu.socket"
        ).stdout

        assert "other_ram: memory@0 {" in printed
        assert "\tram: memory" not in printed

    def test_without_via_it_fails_in_one_line_that_asks_for_it(self, tmp_path):
        description = description_file(tmp_path, TWO_MASTERS)

        result = run_socpuppet("devicetree", description, check=False)

        assert result.returncode != 0
        assert "--via" in result.stderr
        assert "Traceback" not in result.stderr

    def test_a_via_that_names_no_port_fails_in_one_line_that_lists_them(
        self, tmp_path
    ):
        description = description_file(tmp_path, TWO_MASTERS)

        result = run_socpuppet(
            "devicetree", description, "--via", "cpu.sockit", check=False
        )

        assert result.returncode != 0
        assert "cpu.sockit" in result.stderr
        assert "socket" in result.stderr
        assert "Traceback" not in result.stderr


class TestWhenTheDevicetreeCommandIsGivenAFileWhosePlatformIsSomethingElse:
    def test_it_fails_in_one_line_that_says_what_it_found(self, tmp_path):
        description = description_file(tmp_path, "platform = 'spam'")

        result = run_socpuppet("devicetree", description, check=False)

        assert result.returncode != 0
        assert "str" in result.stderr
        assert "Traceback" not in result.stderr


class TestWhenTheDevicetreeCommandIsGivenAFileThatFailsPartWay:
    def test_it_fails_in_one_line_that_gives_the_line_of_the_file(
        self, tmp_path
    ):
        description = description_file(
            tmp_path,
            """
            import socpuppet as sp

            platform = sp.Platform()
            platform.add("plic", sp.Plic(sources=8))
            """,
        )

        result = run_socpuppet("devicetree", description, check=False)

        assert result.returncode != 0
        assert "my_platform.py, line 5" in result.stderr
        assert "sources" in result.stderr
        assert "Traceback" not in result.stderr


class TestWhenTheDevicetreeCommandIsGivenAFileThatIsNotThere:
    def test_it_fails_in_one_line_that_names_the_file(self, tmp_path):
        result = run_socpuppet(
            "devicetree", str(tmp_path / "nowhere.py"), check=False
        )

        assert result.returncode != 0
        assert "nowhere.py" in result.stderr
        assert "Traceback" not in result.stderr


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


def cpu_with_its_peripherals(*, xlen=64):
    """A CPU with a RAM, an interrupt controller, a timer and a UART."""
    platform = sp.Platform()
    cpu = platform.add(
        "cpu", sp.DbtRiseCpu(xlen=xlen, reset_vector=0x8000_0000)
    )
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=0x10_0000))
    plic = platform.add("plic", sp.Plic())
    timer = platform.add("timer", sp.MachineTimer())
    uart = platform.add("uart", sp.Ns16550())
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=0x8000_0000)
    bus.map(plic.socket, base=0x0C00_0000)
    bus.map(timer.socket, base=0x0200_0000)
    bus.map(uart.socket, base=0x1000_0000)
    platform.connect(plic.irq, cpu.irq)
    platform.connect(timer.irq, cpu.timer_irq)
    return platform, bus, plic


class TestWhenAPlatformHasACpuWithItsPeripherals:
    def test_the_devicetree_is_exactly_this_source(self):
        platform, _, _ = cpu_with_its_peripherals()

        assert platform.devicetree() == textwrap.dedent(
            """\
            /dts-v1/;

            / {
            \t#address-cells = <2>;
            \t#size-cells = <2>;

            \tchosen {
            \t\tzephyr,console = &uart;
            \t\tzephyr,shell-uart = &uart;
            \t\tzephyr,sram = &ram;
            \t};

            \tcpus {
            \t\t#address-cells = <1>;
            \t\t#size-cells = <0>;

            \t\tcpu: cpu@0 {
            \t\t\tdevice_type = "cpu";
            \t\t\tcompatible = "riscv";
            \t\t\treg = <0>;
            \t\t\triscv,isa-base = "rv64i";
            \t\t\triscv,isa-extensions = "i", "m", "a", "c", "zicsr", "zifencei";

            \t\t\tcpu_intc: interrupt-controller {
            \t\t\t\tcompatible = "riscv,cpu-intc";
            \t\t\t\t#address-cells = <0>;
            \t\t\t\t#interrupt-cells = <1>;
            \t\t\t\tinterrupt-controller;
            \t\t\t};
            \t\t};
            \t};

            \tram: memory@80000000 {
            \t\tdevice_type = "memory";
            \t\treg = <0x0 0x80000000 0x0 0x100000>;
            \t};

            \tsoc {
            \t\tcompatible = "simple-bus";
            \t\t#address-cells = <2>;
            \t\t#size-cells = <2>;
            \t\tranges;

            \t\ttimer: timer@200bff8 {
            \t\t\tcompatible = "riscv,machine-timer";
            \t\t\treg = <0x0 0x200bff8 0x0 0x8>, <0x0 0x2004000 0x0 0x8>;
            \t\t\treg-names = "mtime", "mtimecmp";
            \t\t\tinterrupts-extended = <&cpu_intc 7>;
            \t\t};

            \t\tplic: interrupt-controller@c000000 {
            \t\t\tcompatible = "sifive,plic-1.0.0";
            \t\t\treg = <0x0 0xc000000 0x0 0x4000000>;
            \t\t\t#address-cells = <0>;
            \t\t\t#interrupt-cells = <2>;
            \t\t\tinterrupt-controller;
            \t\t\triscv,max-priority = <7>;
            \t\t\triscv,ndev = <32>;
            \t\t\tinterrupts-extended = <&cpu_intc 11>;
            \t\t};

            \t\tuart: uart@10000000 {
            \t\t\tcompatible = "ns16550";
            \t\t\treg = <0x0 0x10000000 0x0 0x8>;
            \t\t\treg-shift = <0>;
            \t\t\tclock-frequency = <3686400>;
            \t\t};
            \t};
            };
            """
        )

    @needs_dtc
    def test_the_devicetree_compiler_accepts_it(self, tmp_path):
        platform, _, _ = cpu_with_its_peripherals()

        assert dtc_errors(platform.devicetree(), tmp_path) == ""

    def test_a_32_bit_cpu_is_described_as_one(self):
        platform, _, _ = cpu_with_its_peripherals(xlen=32)

        assert 'riscv,isa-base = "rv32i";' in platform.devicetree()


class TestWhenADevicesInterruptGoesToAPlicSource:
    def test_its_node_names_the_plic_and_the_source(self):
        platform, bus, plic = cpu_with_its_peripherals()
        device = platform.add("device", sp.MachineTimer())
        bus.map(device.socket, base=0x0300_0000)
        platform.connect(device.irq, plic.source5)

        assert "interrupts-extended = <&plic 5 1>;" in platform.devicetree()


class TestWhenAnMsiBridgesLinesGoToPlicSources:
    def test_its_node_is_exactly_this(self):
        platform, bus, plic = cpu_with_its_peripherals()
        msi = platform.add("msi", sp.MsiPlicBridge(vectors=2))
        bus.map(msi.socket, base=0x0300_0000)
        platform.connect(msi.irq0, plic.source4)
        platform.connect(msi.irq1, plic.source9)

        node = textwrap.dedent(
            """\
            msi: msi-controller@3000000 {
            \tcompatible = "socpuppet,msi-plic-bridge";
            \treg = <0x0 0x3000000 0x0 0x4>;
            \tmsi-controller;
            \tinterrupts-extended = <&plic 4 1 &plic 9 1>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()

    def test_its_node_names_the_sources_in_the_order_of_its_vectors(self):
        platform, bus, plic = cpu_with_its_peripherals()
        msi = platform.add("msi", sp.MsiPlicBridge(vectors=2))
        bus.map(msi.socket, base=0x0300_0000)
        # Firmware finds a vector's interrupt by its place in the list, so
        # the list is in the order of the vectors and not of the wiring.
        platform.connect(msi.irq1, plic.source9)
        platform.connect(msi.irq0, plic.source4)

        assert (
            "interrupts-extended = <&plic 4 1 &plic 9 1>;"
            in platform.devicetree()
        )


def cpu_with_a_pcie_root_complex():
    """The CPU and its peripherals, with a PCIe root complex's two windows."""
    platform, bus, _ = cpu_with_its_peripherals()
    root_complex = platform.add("rc", sp.PcieRootComplex())
    bus.map(root_complex.ecam, base=0x3000_0000, size=0x10_0000)
    bus.map(root_complex.mmio, base=0x4000_0000, size=0x20_0000)
    return platform, root_complex


class TestWhenAPlatformHasAPcieRootComplex:
    def test_its_node_is_exactly_this(self):
        platform, _ = cpu_with_a_pcie_root_complex()

        # `reg` is the configuration window, which has room for one bus in
        # each MiB. `ranges` is the memory window: 32-bit memory space
        # (0x2000000), at the same address on the PCIe bus as on the CPU's.
        node = textwrap.dedent(
            """\
            rc: pcie@30000000 {
            \tcompatible = "socpuppet,pcie";
            \treg = <0x0 0x30000000 0x0 0x100000>;
            \tdevice_type = "pci";
            \t#address-cells = <3>;
            \t#size-cells = <2>;
            \tbus-range = <0 0>;
            \tranges = <0x2000000 0x0 0x40000000 0x0 0x40000000 0x0 0x200000>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()

    def test_firmware_is_pointed_at_it_as_the_pcie_controller(self):
        platform, _ = cpu_with_a_pcie_root_complex()

        assert "zephyr,pcie-controller = &rc;" in platform.devicetree()


class TestWhenOnlyOneWindowOfAPcieRootComplexCanBeReached:
    @pytest.mark.parametrize("window", ["ecam", "mmio"])
    def test_the_devicetree_is_the_one_without_the_root_complex(self, window):
        platform, bus, _ = cpu_with_its_peripherals()
        root_complex = platform.add("rc", sp.PcieRootComplex())
        bus.map(getattr(root_complex, window), base=0x3000_0000, size=0x10_0000)

        # Firmware can do nothing with one window and not the other.
        without_it, _, _ = cpu_with_its_peripherals()
        assert platform.devicetree() == without_it.devicetree()


class TestWhenAPcieConfigurationWindowHasRoomForTwoBuses:
    def test_the_root_complexs_node_says_it_holds_two(self):
        platform, bus, _ = cpu_with_its_peripherals()
        root_complex = platform.add("rc", sp.PcieRootComplex())
        bus.map(root_complex.ecam, base=0x3000_0000, size=0x20_0000)
        bus.map(root_complex.mmio, base=0x4000_0000, size=0x20_0000)

        assert "bus-range = <0 1>;" in platform.devicetree()


class TestWhenAPcieConfigurationWindowHasNoRoomForOneBus:
    def test_the_devicetree_is_refused_and_the_error_says_how_big_a_bus_is(
        self,
    ):
        platform, bus, _ = cpu_with_its_peripherals()
        root_complex = platform.add("rc", sp.PcieRootComplex())
        bus.map(root_complex.ecam, base=0x3000_0000, size=0x8_0000)
        bus.map(root_complex.mmio, base=0x4000_0000, size=0x20_0000)

        with pytest.raises(ValueError, match=r"rc\.ecam.*1 MiB"):
            platform.devicetree()


class TestADevicetreeOverlayForOneOfAPlatformsComponents:
    def test_is_exactly_this_source(self):
        platform, root_complex = cpu_with_a_pcie_root_complex()

        # Only what the one component adds: its node, and what `chosen`
        # says of it. The firmware's devicetree has the rest already.
        assert platform.devicetree_overlay([root_complex]) == textwrap.dedent(
            """\
            / {
            \tchosen {
            \t\tzephyr,pcie-controller = &rc;
            \t};

            \tsoc {
            \t\trc: pcie@30000000 {
            \t\t\tcompatible = "socpuppet,pcie";
            \t\t\treg = <0x0 0x30000000 0x0 0x100000>;
            \t\t\tdevice_type = "pci";
            \t\t\t#address-cells = <3>;
            \t\t\t#size-cells = <2>;
            \t\t\tbus-range = <0 0>;
            \t\t\tranges = <0x2000000 0x0 0x40000000 0x0 0x40000000 0x0 0x200000>;
            \t\t};
            \t};
            };
            """
        )


class TestADevicetreeOverlayForAComponentThatFillsNoRole:
    def test_says_nothing_of_what_is_chosen(self):
        platform, bus, plic = cpu_with_its_peripherals()
        msi = platform.add("msi", sp.MsiPlicBridge(vectors=1))
        bus.map(msi.socket, base=0x0300_0000)
        platform.connect(msi.irq0, plic.source4)

        assert "chosen" not in platform.devicetree_overlay([msi])
