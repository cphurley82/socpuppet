"""socpuppet's Zephyr module, as the tests find it."""

import pathlib
import re

import socpuppet

ZEPHYR_MODULE = pathlib.Path(socpuppet.__file__).parent / "zephyr_module"

#: The boards the module carries, by the names Zephyr builds for.
BOARDS = ("socpuppet_host", "socpuppet_ssd", "socpuppet_iomgr")


def kconfig_default(name, under=None):
    """The number socpuppet's SoCs give Zephyr for a Kconfig option.

    `name` is the option without its `CONFIG_`, as the family's
    Kconfig.defconfig has it. `under` is the option a SoC must have for
    the number to be its own, for one of the numbers that the file gives
    inside an `if`: "RISCV_HAS_PLIC" for a SoC with a PLIC, "RISCV_IMSIC"
    for one with an IMSIC. With none, it is a number every SoC is given.
    """
    defaults = (ZEPHYR_MODULE / "soc/socpuppet/Kconfig.defconfig").read_text()
    if under is None:
        # What is left when each inner `if` has been taken out. The file's
        # outermost is of the whole family.
        within = re.sub(
            r"^if (?!SOC_FAMILY_SOCPUPPET)(\w+)$.*?^endif # \1$",
            "",
            defaults,
            flags=re.MULTILINE | re.DOTALL,
        )
    else:
        block = re.search(
            rf"^if {re.escape(under)}$(.*?)^endif # {re.escape(under)}$",
            defaults,
            re.MULTILINE | re.DOTALL,
        )
        assert block is not None, f"Kconfig.defconfig has no `if {under}`"
        within = block.group(1)
    default = re.search(
        rf"^config {re.escape(name)}\s+default (\d+)$", within, re.MULTILINE
    )
    assert default is not None, (
        f"the family's Kconfig.defconfig has no {name}"
        + (f" under {under}" if under else "")
    )
    return int(default.group(1))


def clock_rate():
    """How many times a second Zephyr is told the machine timer counts."""
    return kconfig_default("SYS_CLOCK_HW_CYCLES_PER_SEC")


def the_identities_of_the_hosts_drive():
    """The identities set aside for the drive's vectors, as the shield has them."""
    overlay = (
        ZEPHYR_MODULE
        / "boards/shields/socpuppet_host_drive/socpuppet_host_drive.overlay"
    ).read_text()
    said = re.search(r"socpuppet,msi-identities = <([\d ]+)>;", overlay)
    assert said is not None, "the drive's overlay names no identities"
    return [int(each) for each in said.group(1).split()]


def ram_size(board):
    """How many bytes of memory a board's devicetree gives Zephyr to run in."""
    devicetree = (
        ZEPHYR_MODULE / "boards/socpuppet" / board / f"{board}.dts"
    ).read_text()
    chosen = re.search(r"zephyr,sram = &(\w+);", devicetree)
    assert chosen is not None, f"{board}.dts chooses no zephyr,sram"
    node = re.search(
        # No further than the node's own closing brace.
        rf"{chosen.group(1)}: memory@\w+ {{[^}}]*?"
        r"reg = <0x0 0x[0-9a-f]+ 0x0 (0x[0-9a-f]+)>;",
        devicetree,
    )
    assert node is not None, f"{board}.dts has no node for its zephyr,sram"
    return int(node.group(1), 16)
