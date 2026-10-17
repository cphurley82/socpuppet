"""M25's spike: the host with its virtio slots, set beside QEMU's `virt`.

Reads QEMU's own memory map and interrupt numbers out of `hw/riscv/virt.c`
and `include/hw/riscv/virt.h` (from QBox's copy of QEMU), and the host's
from its description, and prints a Markdown table of where each region of
`virt` is, what the host has there, and whether a stock kernel would find
the same thing. Run it from the top of the repository:

    PYTHONPATH=python uv run python spikes/virtio/compare_virt.py

Not test-first, and nothing outside `spikes/` may use it.
"""

import re
import sys
from pathlib import Path

from socpuppet.boards.host import host
from socpuppet.boards.virtio import Virtio

QEMU = Path("build/qbox/build/_deps/libqemu-src")


def qemu_memmap():
    """`virt_memmap`, as {name: (base, size)}; a size QEMU works out is None."""
    source = (QEMU / "hw/riscv/virt.c").read_text()
    table = source[source.index("virt_memmap[] = {") :]
    table = table[: table.index("};")]
    regions = {}
    for name, base, size in re.findall(
        r"\[VIRT_(\w+)\]\s*=\s*\{\s*(0x[0-9a-fA-F]+),\s*([^}]+?)\s*\}", table
    ):
        size = size.strip()
        regions[name] = (
            int(base, 16),
            int(size, 16) if re.fullmatch(r"0x[0-9a-fA-F]+", size) else None,
        )
    return regions


def qemu_irqs():
    """The interrupt numbers `virt.h` gives its devices."""
    header = (QEMU / "include/hw/riscv/virt.h").read_text()
    return {
        name: int(number, 0)
        for name, number in re.findall(r"(\w+_IRQ) = (\w+)", header)
    }


def main():
    board = host(sbi=True, virtio=Virtio())
    ours = board.platform.address_map(via=board.cpu.socket)
    lines = board.platform.interrupt_map()

    def at(base):
        return [e for e in ours if e.address <= base < e.address + e.size]

    print(
        "| `virt` region | QEMU's base, size | The host there | Same address? |"
    )
    print("|---|---|---|---|")
    for name, (base, size) in qemu_memmap().items():
        found = at(base)
        theirs = f"`{base:#x}`, " + (f"`{size:#x}`" if size else "worked out")
        here = ", ".join(
            f"`{e.component}` (`{e.address:#x}`, `{e.size:#x}`)" for e in found
        )
        same = "—"
        if found:
            e = found[0]
            same = "yes" if e.address == base else "overlaps"
        print(f"| `{name}` | {theirs} | {here or 'nothing'} | {same} |")
    print()
    print("| `virt` line | QEMU's number | The host's |")
    print("|---|---|---|")
    ours_by = {e.line: (e.controller, e.number) for e in lines}
    irqs = qemu_irqs()
    print(
        f"| UART | {irqs['UART0_IRQ']} | "
        f"{ours_by['io.uart.irq'][1]} at `{ours_by['io.uart.irq'][0]}` |"
    )
    for slot, device in enumerate(["rng", "console", "blk", "net", "fs"]):
        controller, number = ours_by[f"io.{device}.irq"]
        print(
            f"| virtio slot {slot} ({device}) | {irqs['VIRTIO_IRQ'] + slot} | "
            f"{number} at `{controller}` |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
