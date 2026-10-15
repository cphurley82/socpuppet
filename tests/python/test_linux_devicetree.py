"""The devicetree in Linux's dialect, which OpenSBI and Linux read.

🎓 A devicetree says what hardware there is, and each operating system has
its own bindings: the names, the numbers of cells and the shapes of nodes
its drivers look for. socpuppet writes Zephyr's unless it is asked for
Linux's. OpenSBI reads Linux's, since it hands the same tree on to Linux.
"""

from processes import run_socpuppet
from test_devicetree import (
    cpu_with_an_aplic,
    cpu_with_its_peripherals,
    description_file,
)


class TestWhenTheDevicetreeIsForLinux:
    def test_the_root_names_the_board_as_it_was_told(self):
        platform, _, _ = cpu_with_its_peripherals()

        devicetree = platform.devicetree(dialect="linux", model="spam")

        # One tab in: a property of the root.
        assert '\n\tmodel = "spam";\n' in devicetree

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
