"""🧦 The interrupt map of a description: whose line is which number."""

import socpuppet as sp
from socpuppet.interrupt_map import InterruptEntry


class TestWhenADevicesLineGoesToASourceOfAPlic:
    def test_the_map_has_the_line_at_that_sources_number(self):
        platform = sp.Platform()
        plic = platform.add("plic", sp.Plic())
        dma = platform.add("dma", sp.DmaEngine())
        platform.connect(dma.irq, plic.source5)

        assert platform.interrupt_map() == [
            InterruptEntry(controller="plic", number=5, line="dma.irq")
        ]


class TestWhenLinesGoToACpusOwnInputs:
    def test_the_map_has_them_at_the_numbers_risc_v_gives_those_inputs(self):
        # 7 is the machine timer's bit in the CPU's interrupt-pending
        # register, and 11 the machine external interrupt's.
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.DbtRiseCpu(xlen=32, reset_vector=0))
        plic = platform.add("plic", sp.Plic())
        timer = platform.add("timer", sp.MachineTimer())
        platform.connect(timer.irq, cpu.timer_irq)
        platform.connect(plic.irq, cpu.irq)

        interrupts = platform.interrupt_map()

        assert (
            InterruptEntry(controller="cpu", number=7, line="timer.irq")
            in interrupts
        )
        assert (
            InterruptEntry(controller="cpu", number=11, line="plic.irq")
            in interrupts
        )


class TestWhenTwoControllersHaveLines:
    def test_the_map_is_in_order_of_controller_and_then_of_number(self):
        platform = sp.Platform()
        plic = platform.add("plic", sp.Plic())
        cpu = platform.add("cpu", sp.DbtRiseCpu(xlen=32, reset_vector=0))
        flash = platform.add("flash", sp.FlashController())
        dma = platform.add("dma", sp.DmaEngine())
        platform.connect(flash.irq, plic.source9)
        platform.connect(dma.irq, plic.source4)
        platform.connect(plic.irq, cpu.irq)

        assert [
            (entry.controller, entry.number)
            for entry in platform.interrupt_map()
        ] == [("cpu", 11), ("plic", 4), ("plic", 9)]


class TestWhenAnInterruptControllerIsAlsoOnABus:
    def test_the_map_has_its_lines_and_not_its_registers(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        bus = platform.add("bus", sp.Router())
        plic = platform.add("plic", sp.Plic())
        dma = platform.add("dma", sp.DmaEngine())
        platform.connect(cpu.socket, bus.target)
        bus.map(plic.socket, base=0x0C00_0000)
        platform.connect(dma.irq, plic.source1)

        assert [entry.line for entry in platform.interrupt_map()] == ["dma.irq"]


class TestWhenALineGoesToAnInputThatHasNoNumber:
    def test_the_map_leaves_it_out(self):
        # 🎭 A script's interrupt inputs have nothing to number them by.
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        dma = platform.add("dma", sp.DmaEngine())
        platform.connect(dma.irq, cpu.irq)

        assert platform.interrupt_map() == []
