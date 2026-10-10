"""The Zephyr module that carries socpuppet's boards, as an installed file."""

import pathlib
import re

import socpuppet as sp
from processes import run_socpuppet
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd
from zephyr_module import ZEPHYR_MODULE, kconfig_default


class TestWhenTheZephyrModuleCommandIsRun:
    def test_it_prints_a_directory_that_zephyr_can_use_as_a_module(self):
        printed = run_socpuppet("zephyr-module").stdout

        module = pathlib.Path(printed.strip())
        assert (module / "zephyr" / "module.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_host/board.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_ssd/board.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_iomgr/board.yml").is_file()


class TestTheBindingsOfTheZephyrModule:
    """🎓 A binding tells Zephyr what a devicetree node of some compatible
    has in it, and a driver says which compatible it is the driver for.
    Three files have to agree for one device, and nothing in a build says
    so until a driver is quietly left out of an image."""

    def test_every_compatible_of_ours_in_a_devicetree_has_a_binding(self):
        assert our_compatibles_in_the_devicetrees() <= set(bindings())

    def test_every_binding_is_in_a_file_named_after_its_compatible(self):
        assert {
            compatible: binding.stem
            for compatible, binding in bindings().items()
        } == {compatible: compatible for compatible in bindings()}

    def test_every_driver_is_for_a_compatible_that_has_a_binding(self):
        # A driver spells its compatible as a C name: `socpuppet_dma_engine`
        # for "socpuppet,dma-engine". Spelled the same way, every binding's
        # compatible is a name a driver could have.
        spelled_as_c = {re.sub(r"[,-]", "_", name) for name in bindings()}

        assert compatibles_the_drivers_are_for() <= spelled_as_c

    def test_every_bindings_vendor_is_one_zephyr_has_been_told_of(self):
        vendors = {compatible.partition(",")[0] for compatible in bindings()}

        assert vendors <= vendors_zephyr_is_told_of()


class TestTheInterruptNumbersZephyrIsTold:
    """🎓 Zephyr numbers interrupts in two levels. The first level is the
    CPU's own inputs, and one of them is the line an interrupt controller
    drives. That controller's sources are the second level, and are
    numbered on from where the first level ends. The SoC's Kconfig says
    where that is, and how many there are, and a board's description says
    the same things its own way."""

    def test_the_second_level_hangs_off_the_input_the_plic_drives(self):
        assert kconfig_default("2ND_LVL_INTR_00_OFFSET") == (
            the_number_a_cpu_knows_its_plic_by()
        )

    def test_the_second_levels_numbers_start_after_the_first_levels(self):
        # The CPU's inputs are numbered from 0 up to the one the PLIC
        # drives, which is the last of them.
        assert kconfig_default("2ND_LVL_ISR_TBL_OFFSET") == (
            the_number_a_cpu_knows_its_plic_by() + 1
        )

    def test_an_interrupt_controller_has_room_for_every_source_of_the_plic(
        self,
    ):
        # And for source 0, which means "none".
        assert kconfig_default("MAX_IRQ_PER_AGGREGATOR") == sp.Plic.SOURCES + 1

    def test_there_are_as_many_interrupts_as_both_levels_have(self):
        assert kconfig_default("NUM_IRQS") == kconfig_default(
            "2ND_LVL_ISR_TBL_OFFSET"
        ) + kconfig_default("MAX_IRQ_PER_AGGREGATOR")


def bindings():
    """The module's bindings, by the compatible each says it is for."""
    found = {}
    for binding in (ZEPHYR_MODULE / "dts/bindings").rglob("*.yaml"):
        said = re.search(
            r"^compatible: \"(.+)\"$", binding.read_text(), re.MULTILINE
        )
        assert said is not None, f"{binding} names no compatible"
        found[said.group(1)] = binding
    return found


def our_compatibles_in_the_devicetrees():
    """Every compatible of socpuppet's own that a devicetree in the module has.

    The boards' devicetrees and the shields' overlays are what firmware is
    built against, and each is generated from a board's description.
    """
    found = set()
    for pattern in ("*.dts", "*.dtsi", "*.overlay"):
        for devicetree in ZEPHYR_MODULE.rglob(pattern):
            found.update(
                re.findall(
                    r'compatible = "(socpuppet,[^"]+)"', devicetree.read_text()
                )
            )
    assert found, "no devicetree in the module has a compatible of ours"
    return found


def compatibles_the_drivers_are_for():
    """What each of the module's drivers says it is the driver for."""
    found = {
        compatible
        for source in (ZEPHYR_MODULE / "drivers").rglob("*.c")
        for compatible in re.findall(
            r"^#define DT_DRV_COMPAT (\w+)$", source.read_text(), re.MULTILINE
        )
    }
    assert found, "no driver in the module says what it is for"
    return found


def vendors_zephyr_is_told_of():
    """The vendors the module gives Zephyr a prefix for."""
    prefixes = ZEPHYR_MODULE / "dts/bindings/vendor-prefixes.txt"
    return {
        line.split()[0]
        for line in prefixes.read_text().splitlines()
        if line and not line.startswith("#")
    }


def the_number_a_cpu_knows_its_plic_by():
    """Which of its CPU's interrupts a board's PLIC drives.

    It is one number for every board with a CPU, and the SSD's is asked.
    """
    (entry,) = (
        entry
        for entry in ssd(host=idle_host).platform.interrupt_map()
        if entry.line.endswith("plic.irq")
    )
    return entry.number
