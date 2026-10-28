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


def cpu_with_its_peripherals(
    *, xlen=64, time_from_the_timer=False, timer_hz=None, **described
):
    """A CPU with a RAM, an interrupt controller, a timer and a UART.

    With `time_from_the_timer`, the CPU reads its `time` register from the
    timer, which counts `timer_hz` times a second if that is said.
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
    timer = platform.add(
        "timer",
        sp.MachineTimer()
        if timer_hz is None
        else sp.MachineTimer(frequency_hz=timer_hz),
    )
    uart = platform.add("uart", sp.Ns16550())
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=0x8000_0000)
    bus.map(plic.socket, base=0x0C00_0000)
    bus.map(timer.socket, base=0x0200_0000)
    bus.map(uart.socket, base=0x1000_0000)
    platform.connect(plic.irq, cpu.irq)
    platform.connect(timer.irq, cpu.timer_irq)
    if time_from_the_timer:
        platform.connect(cpu.time, timer.time)
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


class TestWhenACpuReadsItsTimeFromATimer:
    def test_cpus_says_how_many_times_a_second_the_timer_counts(self):
        platform, _, _ = cpu_with_its_peripherals(
            time_from_the_timer=True, timer_hz=1_000_000
        )

        assert (
            textwrap.indent(
                textwrap.dedent(
                    """\
                cpus {
                \t#address-cells = <1>;
                \t#size-cells = <0>;
                \ttimebase-frequency = <1000000>;
                """
                ),
                "\t",
            )
            in platform.devicetree()
        )


class TestWhenACpuHasSupervisorMode:
    def test_its_node_says_it_translates_addresses_with_sv39(self):
        platform, _, _ = cpu_with_its_peripherals(isa="gc", modes="msu")

        assert 'mmu-type = "riscv,sv39";' in platform.devicetree()


class TestWhenACpuHasMachineModeOnly:
    def test_its_node_says_nothing_of_an_mmu(self):
        platform, _, _ = cpu_with_its_peripherals(isa="imac", modes="m")

        assert "mmu-type" not in platform.devicetree()


@needs_dtc
class TestWhenADevicetreeIsCompiled:
    def test_the_blob_starts_with_the_devicetrees_magic_number(self):
        platform, _, _ = cpu_with_its_peripherals()

        blob = sp.devicetree.compile(platform.devicetree())

        assert blob[:4] == bytes.fromhex("d00dfeed")

    def test_a_source_dtc_refuses_is_refused_in_dtcs_own_words(self):
        with pytest.raises(ValueError, match="syntax error"):
            sp.devicetree.compile("/dts-v1/;\n/ { spam\n")


class TestWhenADevicetreeIsCompiledWithNoDtcInstalled:
    @pytest.mark.usefixtures("dtc_is_not_installed")
    def test_the_error_names_dtc_and_how_to_install_it(self):
        with pytest.raises(FileNotFoundError, match="device-tree-compiler"):
            sp.devicetree.compile("/dts-v1/;\n/ { };\n")


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


class TestWhenACpuHasAFlashOnItsBus:
    def test_its_node_is_the_controllers_with_the_chip_inside(self):
        # 🎓 The controller's node has its registers and the window as its
        # two ranges, named; the chip is a node inside it, at its chip
        # select, with its JEDEC id and its size in bits, which Zephyr's
        # spi_nor driver reads where it would otherwise ask the chip.
        platform, bus, _ = cpu_with_its_peripherals()
        flash = platform.add("flash", sp.SpiFlash(size=0x40_0000))
        bus.map(flash.xip, base=0x1020_0000)
        bus.map(flash.socket, base=0x100D_0000)

        fastest = sp.SpiFlash.FASTEST_HZ
        node = textwrap.dedent(
            f"""\
            flash: spi@100d0000 {{
            \tcompatible = "sifive,spi0";
            \treg = <0x0 0x100d0000 0x0 0x1000>, <0x0 0x10200000 0x0 0x400000>;
            \treg-names = "control", "mem";
            \tclocks = <&flash_clock>;
            \t#address-cells = <1>;
            \t#size-cells = <0>;
            \tflash_chip: flash@0 {{
            \t\tcompatible = "jedec,spi-nor";
            \t\treg = <0>;
            \t\tjedec-id = [ef 40 16];
            \t\tsize = <0x2000000>;
            \t\tspi-max-frequency = <{fastest}>;
            \t}};
            }};
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()

    def test_its_controllers_clock_is_a_fixed_clock_at_the_top_of_the_tree(
        self,
    ):
        # 🎓 A clock that only ever runs at one rate is a fixed clock: a node
        # that says the rate, which a driver reads to set the bus's speed.
        platform, bus, _ = cpu_with_its_peripherals()
        flash = platform.add("flash", sp.SpiFlash(size=0x40_0000))
        bus.map(flash.xip, base=0x1020_0000)
        bus.map(flash.socket, base=0x100D_0000)

        clock = textwrap.dedent(
            f"""\
            flash_clock: flash_clock {{
            \tcompatible = "fixed-clock";
            \t#clock-cells = <0>;
            \tclock-frequency = <{sp.SpiFlash.CLOCK_HZ}>;
            }};
            """
        )
        assert textwrap.indent(clock, "\t") in platform.devicetree()


class TestWhenACpuReachesOnlyAFlashsWindow:
    def test_its_devicetree_has_no_node_for_the_flash(self):
        # A CPU that cannot reach the controller's registers cannot drive
        # it, as a boot ROM, which reads the window, has no need to.
        platform, bus, _ = cpu_with_its_peripherals()
        without = platform.devicetree()
        flash = platform.add("flash", sp.SpiFlash(size=0x40_0000))
        bus.map(flash.xip, base=0x1020_0000)

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


class TestWhenACpuHasAWatchdogOnItsBus:
    def test_it_is_the_alias_watchdog0(self):
        # Zephyr's own watchdog test asks for its device by this alias.
        platform, _, _ = cpu_with_a_watchdog()

        aliases = textwrap.dedent(
            """\
            aliases {
            \twatchdog0 = &wdt;
            };
            """
        )
        assert textwrap.indent(aliases, "\t") in platform.devicetree()


class TestWhenACpuHasAGpioWithItsPinsInterruptsAtPlicSources:
    def test_its_node_has_its_pins_and_an_interrupt_for_each(self):
        # 🎓 Zephyr's driver gives pin n the node's interrupt n, and
        # Zephyr's binding asks for them the short way.
        platform, bus, plic = cpu_with_its_peripherals()
        gpio = platform.add("gpio", sp.Gpio(pins=2))
        bus.map(gpio.socket, base=0x0010_2000)
        platform.connect(gpio.irq0, plic.source6)
        platform.connect(gpio.irq1, plic.source7)

        node = textwrap.dedent(
            """\
            gpio: gpio@102000 {
            \tcompatible = "sifive,gpio0";
            \treg = <0x0 0x102000 0x0 0x1000>;
            \tgpio-controller;
            \t#gpio-cells = <2>;
            \tngpios = <2>;
            \tinterrupt-parent = <&plic>;
            \tinterrupts = <6 1 7 1>;
            };
            """
        )
        assert textwrap.indent(node, "\t\t") in platform.devicetree()


class TestWhenACpuHasAGpioWithAnLedOnAPin:
    def test_the_led_is_in_a_gpio_leds_node_by_its_pin(self):
        # 🎓 An LED is a pin firmware drives; `gpio-leds` says which.
        platform, bus, _ = cpu_with_its_peripherals()
        gpio = platform.add("gpio", sp.Gpio(pins=4, leds=(2,)))
        bus.map(gpio.socket, base=0x0010_2000)

        node = textwrap.dedent(
            """\
            gpio_leds: gpio_leds {
            \tcompatible = "gpio-leds";
            \tgpio_led0: led_0 {
            \t\tgpios = <&gpio 2 0>;
            \t};
            };
            """
        )
        assert textwrap.indent(node, "\t") in platform.devicetree()

    def test_the_led_is_the_alias_led0(self):
        # Zephyr's samples look for the board's first LED by this name.
        platform, bus, _ = cpu_with_its_peripherals()
        gpio = platform.add("gpio", sp.Gpio(pins=4, leds=(2,)))
        bus.map(gpio.socket, base=0x0010_2000)

        assert "\t\tled0 = &gpio_led0;\n" in platform.devicetree()


class TestWhenACpuHasTwoWatchdogsOnItsBus:
    def test_the_one_at_the_lower_address_is_the_alias_watchdog0(self):
        # An alias names one device, as a role in `chosen` does, and goes
        # to the first that can take it.
        platform, bus, _ = cpu_with_its_peripherals()
        bus.map(platform.add("eggs", sp.Watchdog()).socket, base=0x0010_2000)
        bus.map(platform.add("spam", sp.Watchdog()).socket, base=0x0010_1000)

        assert "watchdog0 = &spam;" in platform.devicetree()


def cpu_with_an_imsic(
    *, machine_page_at=0x2400_0000, isa="gc", modes="msu", **described
):
    """A CPU with an IMSIC: both the IMSIC's lines go to the CPU, and the
    CPU's `csr` to the IMSIC.

    The page for the supervisor's messages is on the CPU's bus. The one
    for machine mode's is too, unless `machine_page_at` is None. The CPU
    is the one with supervisor mode unless `isa` and `modes` say another.
    `described` is what to describe the IMSIC with.
    """
    platform = sp.Platform()
    cpu = platform.add(
        "cpu",
        sp.DbtRiseCpu(xlen=64, reset_vector=0x8000_0000, isa=isa, modes=modes),
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

        assert '"zifencei", "smcsrind"' in platform.devicetree()

    def test_a_cpu_with_supervisor_mode_lists_that_modes_way_to_one_as_well(
        self,
    ):
        # Ssaia is supervisor mode's three registers (`siselect`, `sireg`
        # and `stopei`), and what Linux's IMSIC driver looks for.
        platform = cpu_with_an_imsic(isa="gc", modes="msu")

        assert '"smcsrind", "ssaia";' in platform.devicetree()

    def test_a_cpu_with_no_supervisor_mode_does_not(self):
        platform = cpu_with_an_imsic(isa="imac", modes="m")

        devicetree = platform.devicetree()
        assert '"zifencei", "smcsrind";' in devicetree
        assert "ssaia" not in devicetree


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


class TestADevicetreeOverlayForAComponentWithAnAlias:
    def test_gives_the_alias_and_none_of_the_rest(self):
        # The board's own watchdog keeps its alias in the board's tree; the
        # overlay names the one it adds.
        platform, bus, _ = cpu_with_its_peripherals()
        fs = platform.add("fs", sp.VirtioFs(tag="spam", directory="."))
        bus.map(fs.cpu, base=0x0300_0000)
        wdt = platform.add("wdt", sp.Watchdog())
        bus.map(wdt.socket, base=0x0400_0000)

        overlay = platform.devicetree_overlay([fs])

        assert "\taliases {\n\t\tvirtiofs0 = &fs;\n\t};" in overlay
        assert "watchdog0" not in overlay


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


def a_cpu_with_a_virtio_device(name, device, *, chooses=False):
    """A bus master with an APLIC and 🎭 one virtio `device` in slot 0.

    The master is a scripted one, which chooses nothing, unless `chooses`,
    when it is a CPU.
    """
    platform = sp.Platform()
    master = (
        sp.DbtRiseCpu(xlen=64, reset_vector=0x8000_0000)
        if chooses
        else sp.ScriptedBusMaster()
    )
    cpu = platform.add("cpu", master)
    bus = platform.add("bus", sp.Router())
    aplic = platform.add("aplic", sp.Aplic())
    placed = platform.add(name, device)
    platform.connect(cpu.socket, bus.target)
    bus.map(aplic.socket, base=0x0C00_0000)
    bus.map(placed.cpu, base=0x1000_1000)
    platform.connect(placed.irq, aplic.source1)
    platform.connect(placed.dma, bus.add_input())
    return platform, cpu


def a_cpu_with_a_virtio_entropy_device(*, chooses=False):
    return a_cpu_with_a_virtio_device("rng", sp.VirtioRng(), chooses=chooses)


def a_node_of(*lines):
    """A node's source, one line each, as it sits in a tree."""
    return "\n".join(lines)


class TestWhenAPlatformHasAVirtioEntropyDevice:
    def test_in_zephyrs_dialect_its_node_has_a_child_that_says_what_it_is(self):
        # Zephyr's drivers bind to a child of the transport's node, by
        # the device's kind; Linux's bind to the transport's node alone.
        platform, cpu = a_cpu_with_a_virtio_entropy_device()

        assert a_node_of(
            "\t\trng: virtio_mmio@10001000 {",
            '\t\t\tcompatible = "virtio,mmio";',
            "\t\t\treg = <0x0 0x10001000 0x0 0x200>;",
            "\t\t\tinterrupt-parent = <&aplic>;",
            "\t\t\tinterrupts = <1 1 4>;",
            "\t\t\trng_device: virtio-entropy {",
            '\t\t\t\tcompatible = "virtio,device4";',
            "\t\t\t};",
            "\t\t};",
        ) in platform.devicetree(via=cpu.socket)

    def test_in_zephyrs_dialect_the_child_is_the_chosen_entropy_source(self):
        platform, cpu = a_cpu_with_a_virtio_entropy_device(chooses=True)

        assert "zephyr,entropy = &rng_device;" in platform.devicetree(
            via=cpu.socket
        )

    def test_in_linuxs_dialect_its_node_is_the_transports_alone(self):
        platform, cpu = a_cpu_with_a_virtio_entropy_device()

        tree = platform.devicetree(via=cpu.socket, dialect="linux")

        assert (
            a_node_of(
                "\t\trng: virtio_mmio@10001000 {",
                '\t\t\tcompatible = "virtio,mmio";',
                "\t\t\treg = <0x0 0x10001000 0x0 0x200>;",
                "\t\t\tinterrupt-parent = <&aplic>;",
                "\t\t\tinterrupts = <1 4>;",
                "\t\t};",
            )
            in tree
        )
        assert "virtio,device4" not in tree


class TestWhenAPlatformHasAVirtioConsole:
    def test_in_zephyrs_dialect_its_child_is_what_zephyrs_console_binds_to(
        self,
    ):
        # Zephyr's console driver binds to "virtio,console" by name, where
        # its entropy driver binds to the device's number.
        platform, cpu = a_cpu_with_a_virtio_device(
            "console", sp.VirtioConsole()
        )

        assert a_node_of(
            "\t\tconsole: virtio_mmio@10001000 {",
            '\t\t\tcompatible = "virtio,mmio";',
            "\t\t\treg = <0x0 0x10001000 0x0 0x200>;",
            "\t\t\tinterrupt-parent = <&aplic>;",
            "\t\t\tinterrupts = <1 1 4>;",
            "\t\t\tconsole_device: virtio-console {",
            '\t\t\t\tcompatible = "virtio,console";',
            "\t\t\t};",
            "\t\t};",
        ) in platform.devicetree(via=cpu.socket)

    def test_it_is_not_the_chosen_console(self):
        # That is a shield's to say: the 16550 stays the console unless
        # firmware is built to speak through this one.
        platform, cpu = a_cpu_with_a_virtio_device(
            "console", sp.VirtioConsole(), chooses=True
        )

        assert "zephyr,console" not in platform.devicetree(via=cpu.socket)


class TestWhenAPlatformHasAVirtioDisk:
    @pytest.mark.parametrize(
        ("dialect", "cells"), [("zephyr", "1 1 4"), ("linux", "1 4")]
    )
    def test_its_node_is_the_transports_alone_in_either_dialect(
        self, dialect, cells
    ):
        # Zephyr has no driver for a virtio disk, so nothing binds to a
        # child; Linux's and EDK2's find the transport and ask it.
        platform, cpu = a_cpu_with_a_virtio_device(
            "blk", sp.VirtioBlk(blocks=8)
        )

        tree = platform.devicetree(via=cpu.socket, dialect=dialect)

        assert (
            a_node_of(
                "\t\tblk: virtio_mmio@10001000 {",
                '\t\t\tcompatible = "virtio,mmio";',
                "\t\t\treg = <0x0 0x10001000 0x0 0x200>;",
                "\t\t\tinterrupt-parent = <&aplic>;",
                f"\t\t\tinterrupts = <{cells}>;",
                "\t\t};",
            )
            in tree
        )


class TestWhenAPlatformHasAVirtioNetworkDevice:
    def test_in_zephyrs_dialect_its_child_has_the_mac_address(self):
        # Zephyr's driver takes the address from the devicetree, never
        # from the device.
        platform, cpu = a_cpu_with_a_virtio_device(
            "net", sp.VirtioNet(mac=0x0200_5E00_53AA)
        )

        assert a_node_of(
            "\t\t\tnet_device: virtio-net {",
            '\t\t\t\tcompatible = "virtio,net";',
            "\t\t\t\tlocal-mac-address = [02 00 5e 00 53 aa];",
            "\t\t\t};",
        ) in platform.devicetree(via=cpu.socket)

    def test_in_linuxs_dialect_it_has_no_child(self):
        # Linux reads the address from the device's configuration.
        platform, cpu = a_cpu_with_a_virtio_device("net", sp.VirtioNet())

        tree = platform.devicetree(via=cpu.socket, dialect="linux")

        assert (
            a_node_of(
                "\t\tnet: virtio_mmio@10001000 {",
                '\t\t\tcompatible = "virtio,mmio";',
                "\t\t\treg = <0x0 0x10001000 0x0 0x200>;",
                "\t\t\tinterrupt-parent = <&aplic>;",
                "\t\t\tinterrupts = <1 4>;",
                "\t\t};",
            )
            in tree
        )


class TestWhenAPlatformHasAVirtioFileSystemDevice:
    @pytest.mark.parametrize(
        ("dialect", "cells"), [("zephyr", "1 1 4"), ("linux", "1 4")]
    )
    def test_its_node_is_the_transports_alone_in_either_dialect(
        self, dialect, cells
    ):
        # Zephyr's client mounts the transport's device itself, and Linux
        # finds the share by the tag the device gives.
        platform, cpu = a_cpu_with_a_virtio_device(
            "fs", sp.VirtioFs(tag="spam", directory=".")
        )

        assert a_node_of(
            "\t\tfs: virtio_mmio@10001000 {",
            '\t\t\tcompatible = "virtio,mmio";',
            "\t\t\treg = <0x0 0x10001000 0x0 0x200>;",
            "\t\t\tinterrupt-parent = <&aplic>;",
            f"\t\t\tinterrupts = <{cells}>;",
            "\t\t};",
        ) in platform.devicetree(via=cpu.socket, dialect=dialect)

    def test_it_is_the_alias_virtiofs0(self):
        # Zephyr's sample asks for the device by a label of the board's;
        # an alias is the name a board agrees on beforehand.
        platform, cpu = a_cpu_with_a_virtio_device(
            "fs", sp.VirtioFs(tag="spam", directory="."), chooses=True
        )

        assert "\t\tvirtiofs0 = &fs;" in platform.devicetree(via=cpu.socket)
