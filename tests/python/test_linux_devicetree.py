"""The devicetree in Linux's dialect, which OpenSBI and Linux read.

🎓 A devicetree says what hardware there is, and each operating system has
its own bindings: the names, the numbers of cells and the shapes of nodes
its drivers look for. socpuppet writes Zephyr's unless it is asked for
Linux's. OpenSBI reads Linux's, since it hands the same tree on to Linux.
"""

import textwrap

import socpuppet as sp
from processes import run_socpuppet
from socpuppet.regs import system_controller as regs
from test_devicetree import (
    cpu_with_a_pcie_root_complex,
    cpu_with_an_aplic,
    cpu_with_an_imsic,
    cpu_with_its_peripherals,
    description_file,
)


class TestWhenTheDevicetreeIsForLinux:
    def test_the_root_names_the_board_as_it_was_told(self):
        platform, _, _ = cpu_with_its_peripherals()

        devicetree = platform.devicetree(dialect="linux", model="spam")

        # One tab in: a property of the root.
        assert '\n\tmodel = "spam";\n' in devicetree

    def test_the_root_says_it_is_a_socpuppet_platform(self):
        # 🎓 Without one, Linux takes the tree for the empty one it builds
        # in (`_ROOT_FOR_LINUX` in devicetree.py says what follows).
        platform, _, _ = cpu_with_its_peripherals()

        devicetree = platform.devicetree(dialect="linux")

        assert '\n\tcompatible = "socpuppet,platform";\n' in devicetree

    def test_chosen_names_the_console_by_its_path_and_carries_the_command_line(
        self,
    ):
        platform, _, _ = cpu_with_its_peripherals()

        devicetree = platform.devicetree(dialect="linux", bootargs="eggs")

        assert (
            "\tchosen {\n"
            '\t\tbootargs = "eggs";\n'
            '\t\tstdout-path = "/soc/serial@10000000";\n'
            "\t};\n"
        ) in devicetree

    def test_chosen_says_where_the_initramfs_is_in_two_cells_each(self):
        # 🐧 Linux reads where the initramfs starts and ends from these two,
        # a number of as many cells as the property has.
        platform, _, _ = cpu_with_its_peripherals()

        devicetree = platform.devicetree(
            dialect="linux", initrd=(0x8240_0000, 0x1_0000_0010)
        )

        opened = devicetree.index("\tchosen {")
        chosen = devicetree[opened : devicetree.index("\t};\n", opened)]
        assert "\t\tlinux,initrd-start = <0x0 0x82400000>;\n" in chosen
        assert "\t\tlinux,initrd-end = <0x1 0x10>;\n" in chosen

    def test_the_timer_is_an_aclint_mtimer(self):
        platform, _, _ = cpu_with_its_peripherals()

        devicetree = platform.devicetree(dialect="linux")

        assert 'compatible = "riscv,aclint-mtimer";' in devicetree

    def test_an_aplic_names_an_interrupt_by_its_source_and_how_its_line_asks(
        self,
    ):
        # Two cells, where Zephyr's binding has a priority between them.
        devicetree = cpu_with_an_aplic().devicetree(dialect="linux")

        assert "interrupts = <16 4>;" in devicetree

    def test_the_cpu_says_how_fast_its_time_counts_and_how_it_pages(self):
        platform, _, _ = cpu_with_its_peripherals(
            time_from_the_timer=True, timer_hz=1_000_000, isa="gc", modes="msu"
        )

        devicetree = platform.devicetree(dialect="linux")

        assert "timebase-frequency = <1000000>;" in devicetree
        assert 'mmu-type = "riscv,sv39";' in devicetree


class TestWhenAnImsicsTwoPagesAreOnTheCpusBusForLinux:
    """🎓 Linux's binding has a node for each privilege level's interrupt
    file, and the level is said only by which of the CPU's interrupts the
    node names: 11 for machine mode's, 9 for the supervisor's."""

    def test_it_is_a_node_for_each_page_and_exactly_these(self):
        devicetree = cpu_with_an_imsic(identities=127).devicetree(
            dialect="linux"
        )

        nodes = textwrap.dedent(
            """\
            imsic_m: interrupt-controller@24000000 {
            \tcompatible = "riscv,imsics";
            \treg = <0x0 0x24000000 0x0 0x1000>;
            \t#address-cells = <0>;
            \t#interrupt-cells = <0>;
            \tinterrupt-controller;
            \tmsi-controller;
            \t#msi-cells = <0>;
            \triscv,num-ids = <127>;
            \tinterrupts-extended = <&cpu_intc 11>;
            };

            imsic_s: interrupt-controller@28000000 {
            \tcompatible = "riscv,imsics";
            \treg = <0x0 0x28000000 0x0 0x1000>;
            \t#address-cells = <0>;
            \t#interrupt-cells = <0>;
            \tinterrupt-controller;
            \tmsi-controller;
            \t#msi-cells = <0>;
            \triscv,num-ids = <127>;
            \tinterrupts-extended = <&cpu_intc 9>;
            };
            """
        )
        assert textwrap.indent(nodes, "\t\t") in devicetree

    def test_an_aplics_messages_go_to_the_supervisors_page(self):
        # Linux, which drives the APLIC, is the supervisor.
        devicetree = cpu_with_an_aplic().devicetree(dialect="linux")

        assert "msi-parent = <&imsic_s>;" in devicetree


class TestWhenACpuHasASystemControllerForLinux:
    def test_beside_it_are_how_to_reset_the_cpu_and_how_to_switch_it_off(
        self,
    ):
        # 🎓 Two nodes at the top of the tree, which name the system
        # controller's node and say which register to write and what.
        platform, bus, _ = cpu_with_its_peripherals()
        syscon = platform.add("syscon", sp.SystemController())
        bus.map(syscon.socket, base=0x0010_0000)

        nodes = textwrap.dedent(
            f"""\
            syscon_reboot: reboot {{
            \tcompatible = "syscon-reboot";
            \tregmap = <&syscon>;
            \toffset = <{regs.RESET_REQUEST:#x}>;
            \tvalue = <{regs.RESET_REQUEST_RESET:#x}>;
            }};

            syscon_poweroff: poweroff {{
            \tcompatible = "syscon-poweroff";
            \tregmap = <&syscon>;
            \toffset = <{regs.POWER_OFF:#x}>;
            \tvalue = <{regs.POWER_OFF_OFF:#x}>;
            }};
            """
        )
        assert textwrap.indent(nodes, "\t") in platform.devicetree(
            dialect="linux"
        )


class TestWhenACpuHasAFlashOnItsBusForLinux:
    def test_the_devicetree_has_no_node_for_it_yet(self):
        # 🚧 Linux's spi-sifive wants the controller's interrupt, which the
        # flash brings out later in M18; the node comes with it.
        platform, bus, _ = cpu_with_its_peripherals()
        without = platform.devicetree(dialect="linux")
        flash = platform.add("flash", sp.SpiFlash(size=0x40_0000))
        bus.map(flash.xip, base=0x1020_0000)
        bus.map(flash.socket, base=0x100D_0000)

        assert platform.devicetree(dialect="linux") == without


class TestWhenAPlatformHasAPcieRootComplexForLinux:
    def test_it_is_a_generic_ecam_host_and_nothing_of_zephyrs(self):
        # 🎓 ECAM is the standard layout of a PCIe configuration window, and
        # Linux has a driver for any root complex that is that and no more.
        platform, _ = cpu_with_a_pcie_root_complex()

        devicetree = platform.devicetree(dialect="linux")

        assert 'compatible = "pci-host-ecam-generic";' in devicetree
        assert "zephyr" not in devicetree


class TestWhenTheDevicetreeCommandIsAskedForLinuxsDialect:
    def test_it_prints_the_devicetree_in_that_dialect(self, tmp_path):
        description = description_file(
            tmp_path,
            """
            import socpuppet as sp

            platform = sp.Platform()
            cpu = platform.add(
                "cpu", sp.DbtRiseCpu(xlen=64, reset_vector=0x8000_0000)
            )
            bus = platform.add("bus", sp.Router())
            timer = platform.add("timer", sp.MachineTimer())
            platform.connect(cpu.socket, bus.target)
            bus.map(timer.socket, base=0x0200_0000)
            """,
        )

        printed = run_socpuppet(
            "devicetree", description, "--dialect", "linux"
        ).stdout

        assert 'compatible = "riscv,aclint-mtimer";' in printed
