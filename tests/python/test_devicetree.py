import textwrap

import pytest

import socpuppet as sp
from devicetree_compiler import dtc_errors, needs_dtc
from processes import run_socpuppet
from socpuppet.components import wire_out


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


def cpu_with_its_peripherals(*, xlen=64, **described):
    """A CPU with a RAM, an interrupt controller, a timer and a UART.

    `described` is anything more to describe the CPU with than its word
    size.
    """
    platform = sp.Platform()
    cpu = platform.add(
        "cpu",
        sp.DbtRiseCpu(xlen=xlen, reset_vector=0x8000_0000, **described),
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

    def test_a_cpu_with_floating_point_lists_f_and_d_among_its_extensions(self):
        platform, _, _ = cpu_with_its_peripherals(isa="gc", modes="msu")

        assert (
            'riscv,isa-extensions = "i", "m", "a", "f", "d", "c", "zicsr", '
            '"zifencei";' in platform.devicetree()
        )


class TestWhenACpuHasARomBelowItsRam:
    def test_the_devicetree_is_the_one_without_the_rom(self):
        # Firmware is not told of the ROM it was started by: QEMU's `virt`
        # machine has no node for its own either. And `zephyr,sram` goes to
        # the lowest memory, which a ROM at a reset vector would be.
        platform, bus, _ = cpu_with_its_peripherals()
        without = platform.devicetree()
        rom = platform.add("rom", sp.Rom(size=0xF000))
        bus.map(rom.socket, base=0x1000)

        assert platform.devicetree() == without


class TestWhenACpuHasASystemControllerOnItsBus:
    def test_its_node_is_exactly_this(self):
        platform, bus, _ = cpu_with_its_peripherals()
        syscon = platform.add("syscon", sp.SystemController())
        bus.map(syscon.socket, base=0x0010_0000)

        node = textwrap.dedent(
            """\
            syscon: syscon@100000 {
            \tcompatible = "socpuppet,system-controller", "syscon";
            \treg = <0x0 0x100000 0x0 0x20>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()


class TestWhenADevicesInterruptGoesToAPlicSource:
    def test_its_node_names_the_plic_and_the_source(self):
        platform, bus, plic = cpu_with_its_peripherals()
        device = platform.add("device", sp.MachineTimer())
        bus.map(device.socket, base=0x0300_0000)
        platform.connect(device.irq, plic.source5)

        assert "interrupts-extended = <&plic 5 1>;" in platform.devicetree()


class UartWithTwoLines(sp.Ns16550):
    """A UART with a second interrupt line, which no UART here has.

    It is for what a node that names its controller once does with more
    than one interrupt.
    """

    port_specs = (*sp.Ns16550.port_specs, wire_out("irq2", required=False))


def cpu_with_a_uart_of_two_lines():
    """A CPU with two PLICs and a UART that has two interrupt lines.

    Returns the platform, the UART and the two PLICs.
    """
    platform, bus, plic = cpu_with_its_peripherals()
    other_plic = platform.add("other_plic", sp.Plic())
    bus.map(other_plic.socket, base=0x4000_0000)
    uart = platform.add("serial", UartWithTwoLines())
    bus.map(uart.socket, base=0x1100_0000)
    return platform, uart, plic, other_plic


class TestWhenAUartsTwoInterruptsGoToOneController:
    def test_its_node_names_the_controller_once_and_both_interrupts(self):
        platform, uart, plic, _ = cpu_with_a_uart_of_two_lines()
        platform.connect(uart.irq, plic.source10)
        platform.connect(uart.irq2, plic.source11)

        devicetree = platform.devicetree()

        assert "interrupt-parent = <&plic>;" in devicetree
        assert "interrupts = <10 1 11 1>;" in devicetree


class TestWhenAUartsTwoInterruptsGoToTwoControllers:
    def test_the_devicetree_is_refused_and_the_error_names_both(self):
        # A node that names its controller once has no way to say it.
        platform, uart, plic, other_plic = cpu_with_a_uart_of_two_lines()
        platform.connect(uart.irq, plic.source10)
        platform.connect(uart.irq2, other_plic.source11)

        with pytest.raises(ValueError, match="&other_plic") as error:
            platform.devicetree()

        assert "&plic" in str(error.value)
        assert '"serial"' in str(error.value)


class TestWhenAUartsInterruptGoesToAPlicSource:
    def test_its_node_names_the_plic_and_the_source_the_short_way(self):
        # `interrupt-parent` and `interrupts` say what `interrupts-extended`
        # does. Zephyr's Kconfig asks whether a 16550 can interrupt by
        # looking for a property called `interrupts`, and cannot see the
        # other at all.
        platform, _, plic = cpu_with_its_peripherals()
        platform.connect(platform.port("uart.irq"), plic.source10)

        node = textwrap.dedent(
            """\
            uart: uart@10000000 {
            \tcompatible = "ns16550";
            \treg = <0x0 0x10000000 0x0 0x8>;
            \treg-shift = <0>;
            \tclock-frequency = <3686400>;
            \tinterrupt-parent = <&plic>;
            \tinterrupts = <10 1>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()


def cpu_with_a_watchdog():
    """A CPU with a watchdog whose interrupt is at source 4 of its PLIC."""
    platform, bus, plic = cpu_with_its_peripherals()
    wdt = platform.add("wdt", sp.Watchdog())
    bus.map(wdt.socket, base=0x0010_1000)
    platform.connect(wdt.irq, plic.source4)
    return platform, wdt, plic


class TestWhenAWatchdogsInterruptGoesToAPlicSource:
    def test_its_node_is_exactly_this(self):
        # Zephyr's binding for SiFive's watchdog requires a property called
        # `interrupts`, so the interrupt is given the short way.
        platform, _, _ = cpu_with_a_watchdog()

        node = textwrap.dedent(
            """\
            wdt: watchdog@101000 {
            \tcompatible = "sifive,wdt";
            \treg = <0x0 0x101000 0x0 0x1000>;
            \tinterrupt-parent = <&plic>;
            \tinterrupts = <4 1>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()

    def test_its_bite_at_another_source_is_no_interrupt_of_its_node(self):
        # The line that resets is not one firmware has a handler for.
        platform, wdt, plic = cpu_with_a_watchdog()
        platform.connect(wdt.bite, plic.source5)

        assert "interrupts = <4 1>;" in platform.devicetree()


def cpu_with_an_imsic(*, machine_page_at=0x2400_0000, **described):
    """A CPU with an IMSIC: both the IMSIC's lines go to the CPU, and the
    CPU's `csr` to the IMSIC.

    The page for the supervisor's messages is on the CPU's bus. The one
    for machine mode's is too, unless `machine_page_at` is None.
    `described` is what to describe the IMSIC with.
    """
    platform = sp.Platform()
    cpu = platform.add(
        "cpu",
        sp.DbtRiseCpu(xlen=64, reset_vector=0x8000_0000, isa="gc", modes="msu"),
    )
    bus = platform.add("bus", sp.Router())
    imsic = platform.add("imsic", sp.Imsic(**described))
    platform.connect(cpu.socket, bus.target)
    if machine_page_at is not None:
        bus.map(imsic.machine, base=machine_page_at)
    bus.map(imsic.supervisor, base=0x2800_0000)
    platform.connect(imsic.irq, cpu.irq)
    platform.connect(imsic.supervisor_irq, cpu.supervisor_irq)
    platform.connect(cpu.csr, imsic.csr)
    return platform


class TestWhenAnImsicsPageForMachineModeIsOnTheCpusBus:
    def test_its_node_is_of_that_page_and_that_modes_line_and_exactly_this(
        self,
    ):
        # Machine mode is where the firmware of a devicetree runs, so the
        # supervisor's page and line are not in it.
        platform = cpu_with_an_imsic(identities=127)

        node = textwrap.dedent(
            """\
            imsic: interrupt-controller@24000000 {
            \tcompatible = "riscv,imsic";
            \treg = <0x0 0x24000000 0x0 0x1000>;
            \t#address-cells = <0>;
            \t#interrupt-cells = <1>;
            \tinterrupt-controller;
            \tmsi-controller;
            \triscv,num-ids = <127>;
            \triscv,hart-id = <0>;
            \tinterrupts-extended = <&cpu_intc 11>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()


def cpu_with_an_aplic(
    *,
    imsic_page_at=0x2400_0000,
    messages_shifted_by=0,
    own_way_to_the_page=False,
):
    """A CPU with an IMSIC, and an APLIC with a UART's line at source 16.

    The APLIC's messages go onto the CPU's bus. The IMSIC's page for the
    supervisor's messages is there, and the one for machine mode's is too
    unless `imsic_page_at` is None.

    With `messages_shifted_by`, the messages go through a router first
    that has the CPU's bus that far up, so that the APLIC finds everything
    at a higher address than the CPU does. With `own_way_to_the_page`, the
    APLIC has the page for machine mode on a router of its own, at
    0x2400_0000, whether or not the CPU has it.
    """
    platform = sp.Platform()
    cpu = platform.add(
        "cpu",
        sp.DbtRiseCpu(xlen=64, reset_vector=0x8000_0000, isa="gc", modes="msu"),
    )
    bus = platform.add("bus", sp.Router())
    imsic = platform.add("imsic", sp.Imsic())
    aplic = platform.add("aplic", sp.Aplic())
    uart = platform.add("uart", sp.Ns16550())
    platform.connect(cpu.socket, bus.target)
    if imsic_page_at is not None:
        bus.map(imsic.machine, base=imsic_page_at)
    bus.map(imsic.supervisor, base=0x2800_0000)
    bus.map(aplic.socket, base=0x0C00_0000)
    bus.map(uart.socket, base=0x1000_0000)
    platform.connect(imsic.irq, cpu.irq)
    platform.connect(cpu.csr, imsic.csr)
    if messages_shifted_by or own_way_to_the_page:
        up = platform.add("up", sp.Router())
        platform.connect(aplic.msi, up.target)
        if own_way_to_the_page:
            up.map(imsic.machine, base=0x2400_0000)
        else:
            up.map(
                bus.add_input(), base=messages_shifted_by, size=0x1_0000_0000
            )
    else:
        platform.connect(aplic.msi, bus.add_input())
    platform.connect(uart.irq, aplic.source16)
    return platform


class TestWhenAnAplicsMessagesReachAnImsic:
    def test_its_node_names_the_imsic_as_where_they_go_and_is_exactly_this(
        self,
    ):
        platform = cpu_with_an_aplic()

        node = textwrap.dedent(
            """\
            aplic: interrupt-controller@c000000 {
            \tcompatible = "riscv,aplic";
            \treg = <0x0 0xc000000 0x0 0x8000>;
            \t#address-cells = <0>;
            \t#interrupt-cells = <3>;
            \tinterrupt-controller;
            \triscv,num-sources = <31>;
            \tmsi-parent = <&imsic>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()

    def test_a_device_at_one_of_its_sources_names_it_the_source_and_its_level(
        self,
    ):
        # The source's number, a priority, and how the line asks: 4 is the
        # devicetree's number for "while it is high".
        devicetree = cpu_with_an_aplic().devicetree()

        assert "interrupt-parent = <&aplic>;" in devicetree
        assert "interrupts = <16 1 4>;" in devicetree


class TestWhenTwoAplicsOfOneCpuHaveALineAtTheSameSource:
    def test_the_devicetree_is_refused_and_the_error_names_both_lines(self):
        # Firmware that knows an interrupt by one number finds its APLIC by
        # that number, and could not tell these two apart.
        platform = cpu_with_an_aplic()
        bus = platform.port("bus.target").placed
        eggs_aplic = platform.add("eggs_aplic", sp.Aplic())
        eggs = platform.add("eggs", sp.Ns16550())
        bus.map(eggs_aplic.socket, base=0x0D00_0000)
        platform.connect(eggs_aplic.msi, bus.add_input())
        platform.connect(eggs.irq, eggs_aplic.source16)

        with pytest.raises(ValueError, match="interrupt 16") as refused:
            platform.devicetree()

        assert "uart.irq" in str(refused.value)
        assert "eggs.irq" in str(refused.value)


class TestWhenTwoAplicsOfOneCpuHaveLinesAtDifferentSources:
    def test_each_devices_node_names_its_own_aplic_and_source(self):
        platform = cpu_with_an_aplic()
        bus = platform.port("bus.target").placed
        eggs_aplic = platform.add("eggs_aplic", sp.Aplic())
        eggs = platform.add("eggs", sp.Ns16550())
        bus.map(eggs_aplic.socket, base=0x0D00_0000)
        bus.map(eggs.socket, base=0x1000_1000)
        platform.connect(eggs_aplic.msi, bus.add_input())
        platform.connect(eggs.irq, eggs_aplic.source17)

        devicetree = platform.devicetree()

        assert "interrupt-parent = <&aplic>;\n\t\t\tinterrupts = <16 1 4>;" in (
            devicetree
        )
        assert (
            "interrupt-parent = <&eggs_aplic>;\n\t\t\tinterrupts = <17 1 4>;"
            in devicetree
        )


class TestWhenAnAplicsMessagesReachNoPageForMachineMode:
    def test_its_node_names_nowhere_for_them_to_go(self):
        # The devicetree is machine mode's, and an IMSIC that mode cannot
        # be sent messages at has no node in it to name.
        devicetree = cpu_with_an_aplic(imsic_page_at=None).devicetree()

        assert 'compatible = "riscv,aplic";' in devicetree
        assert "msi-parent" not in devicetree


class TestWhenAnAplicsMessagesReachAnImsicsPageThatTheCpuDoesNot:
    def test_its_node_names_nowhere_for_them_to_go(self):
        # The IMSIC has no node in the CPU's devicetree to name.
        devicetree = cpu_with_an_aplic(
            imsic_page_at=None, own_way_to_the_page=True
        ).devicetree()

        assert 'compatible = "riscv,aplic";' in devicetree
        assert "msi-parent" not in devicetree


class TestWhenAnAplicFindsTheImsicsPageAtAnotherAddressThanTheCpuDoes:
    def test_the_devicetree_is_refused_and_the_error_gives_both_addresses(self):
        # Firmware reads where the page is from the CPU's devicetree and
        # tells the APLIC to send there.
        platform = cpu_with_an_aplic(messages_shifted_by=0x1_0000_0000)

        with pytest.raises(ValueError, match="0x124000000") as error:
            platform.devicetree()

        assert "0x24000000" in str(error.value)
        assert '"aplic"' in str(error.value)


class TestWhenACpusCsrGoesToAnImsic:
    def test_its_node_lists_the_extension_that_reaches_one(self):
        # Smcsrind is the window onto another block's registers (`miselect`
        # and `mireg`), and what Zephyr switches its IMSIC driver on for.
        platform = cpu_with_an_imsic()

        assert '"zifencei", "smcsrind";' in platform.devicetree()


class TestWhenOnlyAnImsicsPageForTheSupervisorIsOnTheCpusBus:
    def test_the_devicetree_has_no_node_for_it(self):
        platform = cpu_with_an_imsic(machine_page_at=None)

        assert "imsic" not in platform.devicetree()


class TestWhenAnSsdsDevicesAreOnItsCpusBus:
    # The three devices an SSD's firmware drives. Each has a node for its
    # register block, with the PLIC source its line goes to.

    def test_the_nvme_frontends_node_is_exactly_this(self):
        platform, bus, plic = cpu_with_its_peripherals()
        frontend = platform.add("frontend", sp.NvmeFrontend())
        bus.map(frontend.cpu, base=0x1001_0000)
        platform.connect(frontend.cpu_irq, plic.source1)

        node = textwrap.dedent(
            """\
            frontend: nvme-frontend@10010000 {
            \tcompatible = "socpuppet,nvme-frontend";
            \treg = <0x0 0x10010000 0x0 0x80>;
            \tinterrupts-extended = <&plic 1 1>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()

    def test_the_dma_engines_node_is_exactly_this(self):
        platform, bus, plic = cpu_with_its_peripherals()
        dma = platform.add("dma", sp.DmaEngine())
        bus.map(dma.cpu, base=0x1002_0000)
        platform.connect(dma.irq, plic.source2)

        node = textwrap.dedent(
            """\
            dma: dma-controller@10020000 {
            \tcompatible = "socpuppet,dma-engine";
            \treg = <0x0 0x10020000 0x0 0x20>;
            \tinterrupts-extended = <&plic 2 1>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()

    def test_the_flash_controllers_node_is_exactly_this(self):
        platform, bus, plic = cpu_with_its_peripherals()
        flash = platform.add("flash", sp.FlashController())
        bus.map(flash.cpu, base=0x1003_0000)
        platform.connect(flash.irq, plic.source3)

        node = textwrap.dedent(
            """\
            flash: nand-controller@10030000 {
            \tcompatible = "socpuppet,flash-controller";
            \treg = <0x0 0x10030000 0x0 0x30>;
            \tinterrupts-extended = <&plic 3 1>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()


class TestWhenOnlyTheHostsSideOfAnNvmeFrontendCanBeReached:
    # To a host the frontend is an NVMe drive's registers, which a PCIe
    # scan finds. The node is for the SSD's own firmware.
    def test_it_has_no_node(self):
        platform, bus, _ = cpu_with_its_peripherals()
        frontend = platform.add("frontend", sp.NvmeFrontend())
        bus.map(frontend.bar0, base=0x1001_0000)
        without_it, _, _ = cpu_with_its_peripherals()

        assert platform.devicetree() == without_it.devicetree()


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
        # A second timer, which is no console and no memory.
        platform, bus, _ = cpu_with_its_peripherals()
        device = platform.add("device", sp.MachineTimer())
        bus.map(device.socket, base=0x0300_0000)

        assert "chosen" not in platform.devicetree_overlay([device])


def a_manager_die_with_the_real_link():
    """A CPU on the IO die with the link's registers at 0x1001_0000."""
    platform = sp.Platform()
    compute = platform.group("compute")
    io = platform.group("io")
    cpu = io.add("cpu", sp.ScriptedBusMaster())
    bus = io.add("bus", sp.Router())
    link = platform.link("d2d", sp.D2dLink(), compute, io)
    platform.connect(cpu.socket, bus.target)
    bus.map(link.b.sideband, base=0x1001_0000)
    return platform, cpu


class TestWhenTheRealLinksRegistersAreInAFirmwaresView:
    def test_the_link_is_a_node_firmware_can_find(self):
        platform, cpu = a_manager_die_with_the_real_link()

        assert "ucie-link@10010000 {" in platform.devicetree(via=cpu.socket)

    def test_it_says_what_it_is_and_that_it_resets_one_thing(self):
        platform, cpu = a_manager_die_with_the_real_link()

        tree = platform.devicetree(via=cpu.socket)
        assert 'compatible = "socpuppet,ucie-link";' in tree
        assert "#reset-cells = <1>;" in tree

    @needs_dtc
    def test_the_devicetree_compiler_takes_it(self, tmp_path):
        platform, cpu = a_manager_die_with_the_real_link()

        assert dtc_errors(platform.devicetree(via=cpu.socket), tmp_path) == ""
