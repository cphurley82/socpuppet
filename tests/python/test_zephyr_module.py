"""The Zephyr module that carries socpuppet's boards, as an installed file."""

import pathlib
import re

import socpuppet as sp
from processes import run_socpuppet
from zephyr_module import ZEPHYR_MODULE, kconfig_default


class TestWhenTheZephyrModuleCommandIsRun:
    def test_it_prints_a_directory_that_zephyr_can_use_as_a_module(self):
        printed = run_socpuppet("zephyr-module").stdout

        module = pathlib.Path(printed.strip())
        assert (module / "zephyr" / "module.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_host/board.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_ssd/board.yml").is_file()
        assert (module / "boards/socpuppet/socpuppet_iomgr/board.yml").is_file()


def compatible_of(binding):
    """What a binding file says it is the binding of."""
    said = re.search(
        r"^compatible: \"(.+)\"$", binding.read_text(), re.MULTILINE
    )
    assert said is not None, f"{binding} names no compatible"
    return said.group(1)


def bindings():
    """The module's bindings, by the compatible each is named after."""
    return {
        binding.stem: binding
        for binding in (ZEPHYR_MODULE / "dts/bindings").rglob("*.yaml")
    }


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
    return found


class TestTheBindingsOfTheZephyrModule:
    """🎓 A binding tells Zephyr what a devicetree node of some compatible
    has in it, and a driver says which compatible it is the driver for.
    Three files have to agree for one device, and nothing in a build says
    so until a driver is quietly left out of an image."""

    def test_every_compatible_of_ours_in_a_devicetree_has_a_binding(self):
        assert our_compatibles_in_the_devicetrees() <= set(bindings())

    def test_every_binding_is_in_a_file_named_after_its_compatible(self):
        assert {
            name: compatible_of(binding) for name, binding in bindings().items()
        } == {name: name for name in bindings()}

    def test_every_driver_is_for_a_compatible_that_has_a_binding(self):
        # A driver spells its compatible as a C name: `socpuppet_dma_engine`
        # for "socpuppet,dma-engine". Spelled the same way, every binding's
        # compatible is a name a driver could have.
        spelled_as_c = {re.sub(r"[,-]", "_", name) for name in bindings()}
        drivers_are_for = {
            compatible
            for source in (ZEPHYR_MODULE / "drivers").rglob("*.c")
            for compatible in re.findall(
                r"^#define DT_DRV_COMPAT (\w+)$",
                source.read_text(),
                re.MULTILINE,
            )
        }

        assert drivers_are_for
        assert drivers_are_for <= spelled_as_c

    def test_every_bindings_vendor_is_one_zephyr_has_been_told_of(self):
        told_of = {
            line.split()[0]
            for line in (ZEPHYR_MODULE / "dts/bindings/vendor-prefixes.txt")
            .read_text()
            .splitlines()
            if line and not line.startswith("#")
        }

        assert {name.partition(",")[0] for name in bindings()} <= told_of


class TestTheInterruptNumbersZephyrIsTold:
    """🎓 Zephyr numbers interrupts in two levels. The first level is the
    CPU's own inputs, and one of them is the line an interrupt controller
    drives. That controller's sources are the second level, and are
    numbered on from where the first level ends. The SoC's Kconfig says
    where that is, and how many there are, and the platform description
    says the same things its own way."""

    def test_the_second_level_hangs_off_the_cpus_external_interrupt(self):
        cpu = sp.DbtRiseCpu(xlen=32, reset_vector=0)

        assert kconfig_default(
            "2ND_LVL_INTR_00_OFFSET"
        ) == cpu.interrupt_number("irq")

    def test_an_interrupt_controller_has_room_for_every_source_of_the_plic(
        self,
    ):
        # And for source 0, which means "none".
        assert kconfig_default("MAX_IRQ_PER_AGGREGATOR") == sp.Plic.SOURCES + 1

    def test_there_are_as_many_interrupts_as_both_levels_have(self):
        assert kconfig_default("NUM_IRQS") == kconfig_default(
            "2ND_LVL_ISR_TBL_OFFSET"
        ) + kconfig_default("MAX_IRQ_PER_AGGREGATOR")

    def test_the_second_levels_numbers_start_after_the_first_levels(self):
        # The CPU's inputs are numbered from 0 up to the external
        # interrupt, which is the last of them.
        cpu = sp.DbtRiseCpu(xlen=32, reset_vector=0)

        assert (
            kconfig_default("2ND_LVL_ISR_TBL_OFFSET")
            == cpu.interrupt_number("irq") + 1
        )
